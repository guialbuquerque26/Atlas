"""Sobe, acompanha e derruba todos os serviços do Atlas de uma vez.

O gerenciador resolve três problemas que o `ollama serve` + dois terminais
não resolvem sozinhos:

1. **Ordem e dependência** — API e interface só sobem depois do Ollama
   responder; nada de erro silencioso porque o modelo ainda não estava no ar.
2. **Adoção** — se o Ollama já estiver rodando (serviço do Windows, outro
   terminal), ele é reaproveitado e nunca derrubado pelo `parar`.
3. **Rastreio** — cada processo grava PID em `data/run/` e log em
   `data/logs/`, então `status` e `parar` funcionam em qualquer terminal novo.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import httpx

from atlas.config import RAIZ, settings
from atlas.supervisor.definicoes import (
    API,
    INTERFACE,
    MODELOS_NECESSARIOS,
    OLLAMA,
    SERVICOS,
    Servico,
)

# ---------------------------------------------------------------- sondagens


def porta_ocupada(porta: int, host: str = "127.0.0.1") -> bool:
    """Alguém está escutando nesta porta?"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        return s.connect_ex((host, porta)) == 0


# O /health da API consulta o Ollama, que pode estar carregando um modelo;
# 3 segundos não bastam e produziriam falso negativo.
ESPERA_SAUDE_S = 15.0


def responde_saude(servico: Servico, timeout: float = ESPERA_SAUDE_S) -> bool:
    """O serviço responde HTTP no endpoint de saúde?"""
    try:
        resposta = httpx.get(servico.url_saude, timeout=timeout)
        return resposta.status_code < 500
    except httpx.HTTPError:
        return False


def esta_no_ar(servico: Servico) -> bool:
    return porta_ocupada(servico.porta) and responde_saude(servico)


def pid_na_porta(porta: int) -> int | None:
    """Descobre qual processo escuta na porta.

    O `python.exe` do venv é um lançador: o PID que o Popen devolve não é o do
    processo que de fato serve. Perguntar ao sistema quem está na porta é o
    único jeito confiável de encontrar o serviço para encerrá-lo.
    """
    if sys.platform != "win32":
        return None
    try:
        saida = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=15
        ).stdout
    except (subprocess.SubprocessError, OSError):
        return None

    for linha in saida.splitlines():
        campos = linha.split()
        if len(campos) < 5 or campos[3] != "LISTENING":
            continue
        endereco = campos[1]
        if endereco.rsplit(":", 1)[-1] != str(porta):
            continue
        try:
            return int(campos[4])
        except ValueError:
            continue
    return None


# ------------------------------------------------------------ registro de PID


def _registrar_pid(servico: Servico, pid: int, adotado: bool) -> None:
    servico.arquivo_pid.write_text(
        json.dumps(
            {
                "pid": pid,
                "adotado": adotado,
                "porta": servico.porta,
                "iniciado_em": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _ler_pid(servico: Servico) -> dict | None:
    if not servico.arquivo_pid.exists():
        return None
    try:
        return json.loads(servico.arquivo_pid.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _esquecer_pid(servico: Servico) -> None:
    servico.arquivo_pid.unlink(missing_ok=True)


# --------------------------------------------------------------- ciclo de vida


def _iniciar_processo(servico: Servico) -> subprocess.Popen:
    """Dispara o processo desanexado, com a saída redirecionada para o log."""
    servico.arquivo_log.parent.mkdir(parents=True, exist_ok=True)
    log = servico.arquivo_log.open("a", encoding="utf-8", errors="replace")
    log.write(f"\n{'=' * 70}\n{datetime.now():%Y-%m-%d %H:%M:%S} — iniciando {servico.nome}\n")
    log.flush()

    ambiente = {**os.environ, "PYTHONUNBUFFERED": "1", **servico.variaveis_ambiente}

    def _abrir(criacao: int) -> subprocess.Popen:
        return subprocess.Popen(
            servico.comando,
            cwd=RAIZ,
            stdout=log,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=ambiente,
            creationflags=criacao,
            start_new_session=(sys.platform != "win32"),
        )

    if sys.platform != "win32":
        return _abrir(0)

    # Só o grupo novo de processos: basta para o serviço sobreviver ao terminal
    # e para que um Ctrl+C aqui não o derrube. DETACHED_PROCESS e
    # CREATE_BREAKAWAY_FROM_JOB foram testados e derrubam uvicorn e Gradio
    # quando o terminal que os iniciou termina.
    return _abrir(subprocess.CREATE_NEW_PROCESS_GROUP)


def _aguardar(
    servico: Servico, processo: subprocess.Popen | None, limite_s: int | None = None
) -> bool:
    """Espera o healthcheck responder, desistindo se o processo morrer antes."""
    limite = time.monotonic() + (limite_s or servico.espera_s)
    while time.monotonic() < limite:
        if processo is not None and processo.poll() is not None:
            return False
        if esta_no_ar(servico):
            return True
        time.sleep(1.0)
    return False


def _encerrar_pid(pid: int) -> bool:
    """Encerra o processo e toda a sua árvore de filhos."""
    if sys.platform == "win32":
        resultado = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
        )
        return resultado.returncode == 0
    try:
        os.kill(pid, 15)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def _processo_vivo(pid: int) -> bool:
    if sys.platform == "win32":
        saida = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        ).stdout
        return str(pid) in saida
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


# ------------------------------------------------------------------ modelos


def modelos_faltando() -> list[tuple[str, str]]:
    """Modelos declarados no .env que ainda não foram baixados no Ollama."""
    try:
        resposta = httpx.get(f"{OLLAMA.url}/api/tags", timeout=10.0)
        resposta.raise_for_status()
        instalados = [m["name"] for m in resposta.json().get("models", [])]
    except (httpx.HTTPError, KeyError, ValueError):
        return []

    ausentes = []
    for rotulo, modelo in MODELOS_NECESSARIOS:
        base = modelo.split(":")[0]
        if not any(m.split(":")[0] == base for m in instalados):
            ausentes.append((rotulo, modelo))
    return ausentes


def baixar_modelos(modelos: list[tuple[str, str]]) -> None:
    for rotulo, modelo in modelos:
        print(f"  baixando {rotulo}: {modelo} (pode demorar alguns minutos)")
        subprocess.run([OLLAMA.comando[0], "pull", modelo], check=False)


# --------------------------------------------------------------------- ações


@dataclass
class EstadoServico:
    servico: Servico
    no_ar: bool
    pid: int | None
    adotado: bool

    @property
    def rotulo(self) -> str:
        if not self.no_ar:
            return "parado"
        return "adotado" if self.adotado else "no ar"


def coletar_estado() -> list[EstadoServico]:
    estados = []
    for servico in SERVICOS:
        registro = _ler_pid(servico)
        estados.append(
            EstadoServico(
                servico=servico,
                no_ar=esta_no_ar(servico),
                pid=(registro or {}).get("pid"),
                adotado=bool((registro or {}).get("adotado")),
            )
        )
    return estados


def _conferir_modelos(baixar_ausentes: bool) -> None:
    """Avisa (ou resolve) modelos do .env que ainda não estão no Ollama."""
    ausentes = modelos_faltando()
    if not ausentes:
        return
    if baixar_ausentes:
        baixar_modelos(ausentes)
        return
    print(f"  [aviso]   modelos ausentes: {', '.join(m for _, m in ausentes)}")
    print("            rode novamente com --baixar-modelos")


def iniciar(
    nomes: list[str] | None = None,
    baixar_ausentes: bool = False,
    abrir_navegador: bool = True,
) -> int:
    """Sobe os serviços na ordem declarada. Devolve o código de saída."""
    alvos = [s for s in SERVICOS if not nomes or s.nome in nomes]
    falhas: list[str] = []

    print(f"\nAtlas — subindo {len(alvos)} serviço(s)\n{'-' * 60}")

    for servico in alvos:
        if esta_no_ar(servico):
            print(f"  [ok]      {servico.nome:<10} já estava no ar em {servico.url}")
            if _ler_pid(servico) is None:
                _registrar_pid(servico, pid=0, adotado=True)
            if servico is OLLAMA:
                _conferir_modelos(baixar_ausentes)
            continue

        if not servico.disponivel_no_sistema():
            print(f"  [FALHA]   {servico.nome:<10} executável não encontrado: {servico.comando[0]}")
            falhas.append(servico.nome)
            continue

        if porta_ocupada(servico.porta):
            # Pode ser uma instância nossa ainda subindo. Dá uma última chance
            # antes de acusar conflito de porta.
            print(f"  [...]     {servico.nome:<10} porta ocupada, aguardando", end="", flush=True)
            if _aguardar(servico, processo=None, limite_s=20):
                print(f"\r  [ok]      {servico.nome:<10} já estava no ar em {servico.url}      ")
                if _ler_pid(servico) is None:
                    _registrar_pid(servico, pid=0, adotado=True)
                continue
            print(
                f"\r  [FALHA]   {servico.nome:<10} porta {servico.porta} ocupada por outro "
                f"programa que não responde ao healthcheck"
            )
            falhas.append(servico.nome)
            continue

        print(f"  [...]     {servico.nome:<10} iniciando", end="", flush=True)
        processo = _iniciar_processo(servico)
        if _aguardar(servico, processo):
            _registrar_pid(servico, processo.pid, adotado=False)
            print(f"\r  [ok]      {servico.nome:<10} {servico.url} (pid {processo.pid})      ")
        else:
            falhas.append(servico.nome)
            print(f"\r  [FALHA]   {servico.nome:<10} não respondeu em {servico.espera_s}s      ")
            print(f"            veja o log: {servico.arquivo_log}")
            if processo.poll() is None:
                _encerrar_pid(processo.pid)

        # Modelos só podem ser verificados depois que o Ollama está de pé.
        if servico is OLLAMA and servico.nome not in falhas:
            _conferir_modelos(baixar_ausentes)

    tudo_no_ar = _imprimir_painel()

    if tudo_no_ar and abrir_navegador and INTERFACE in alvos:
        webbrowser.open(INTERFACE.url)

    essenciais = [n for n in falhas if next(s for s in SERVICOS if s.nome == n).essencial]
    return 1 if essenciais else 0


def parar(nomes: list[str] | None = None, incluir_externos: bool = False) -> int:
    """Derruba os serviços iniciados pelo Atlas. Externos adotados ficam de pé."""
    alvos = [s for s in reversed(SERVICOS) if not nomes or s.nome in nomes]
    print(f"\nAtlas — parando serviços\n{'-' * 60}")

    for servico in alvos:
        registro = _ler_pid(servico)

        if registro and registro.get("adotado"):
            if servico.externo and not incluir_externos:
                print(f"  [mantido] {servico.nome:<10} já rodava antes do Atlas")
                _esquecer_pid(servico)
                continue

        # Encerra tanto o lançador registrado quanto quem de fato ocupa a porta:
        # com o venv do Windows esses dois PIDs costumam ser diferentes.
        alvos_pid = []
        registrado = (registro or {}).get("pid") or 0
        if registrado:
            alvos_pid.append(registrado)
        ocupante = pid_na_porta(servico.porta)
        if ocupante and ocupante not in alvos_pid:
            alvos_pid.append(ocupante)

        encerrados = [p for p in alvos_pid if _processo_vivo(p) and _encerrar_pid(p)]

        if encerrados:
            print(
                f"  [ok]      {servico.nome:<10} encerrado "
                f"(pid {', '.join(str(p) for p in encerrados)})"
            )
        elif porta_ocupada(servico.porta):
            print(
                f"  [aviso]   {servico.nome:<10} porta {servico.porta} segue ocupada por um "
                f"processo que o Atlas não conseguiu encerrar"
            )
        else:
            print(f"  [ok]      {servico.nome:<10} já estava parado")
        _esquecer_pid(servico)

    print()
    return 0


def _imprimir_painel() -> bool:
    """Mostra o estado final. Devolve True se todos os serviços estão no ar."""
    estados = coletar_estado()
    print(f"{'-' * 60}")
    for estado in estados:
        marca = "•" if estado.no_ar else "×"
        print(f"  {marca} {estado.servico.nome:<10} {estado.rotulo:<9} {estado.servico.url}")
    print(f"{'-' * 60}")

    tudo_no_ar = all(e.no_ar for e in estados)
    if tudo_no_ar:
        print(f"  Interface .... {INTERFACE.url}")
        print(f"  API docs ..... {API.url}/docs")
        print(f"  Logs ......... {settings.logs_dir}")
        print("  Para parar ... python -m atlas.supervisor parar")
    print()
    return tudo_no_ar


def status() -> int:
    print(f"\nAtlas — estado dos serviços\n{'-' * 60}")
    estados = coletar_estado()
    for estado in estados:
        marca = "•" if estado.no_ar else "×"
        pid = f"pid {estado.pid}" if estado.pid else ""
        print(
            f"  {marca} {estado.servico.nome:<10} {estado.rotulo:<9} "
            f"{estado.servico.url:<28} {pid}"
        )
        print(f"      {estado.servico.descricao}")

    if estados[0].no_ar:
        ausentes = modelos_faltando()
        if ausentes:
            print(f"\n  modelos ausentes: {', '.join(m for _, m in ausentes)}")
        else:
            print("\n  modelos: todos presentes")
    print()
    return 0 if all(e.no_ar for e in estados) else 1


def caminho_log(nome: str) -> Path:
    from atlas.supervisor.definicoes import por_nome

    return por_nome(nome).arquivo_log
