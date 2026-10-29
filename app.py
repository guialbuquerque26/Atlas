"""Atlas — ponto de entrada único da aplicação.

    python app.py                 sobe tudo e fica supervisionando (Ctrl+C derruba)
    python app.py --sem-navegador
    python app.py --baixar-modelos
    python app.py status
    python app.py parar
    python app.py logs api --linhas 60

Diferença para `python -m atlas.supervisor iniciar`: aquele sobe os processos e
sai, deixando-os órfãos. Aqui o controller **fica**: vigia a saúde de cada
serviço, recoloca de pé o que cair e, ao receber Ctrl+C/SIGTERM, derruba na
ordem inversa o que ele mesmo subiu (serviços que já rodavam antes são
preservados). É o comportamento que se espera de quem "starta a aplicação".
"""

from __future__ import annotations

import argparse
import signal
import sys
import threading

from atlas import __version__
from atlas.config import settings
from atlas.supervisor import gerenciador
from atlas.supervisor.definicoes import SERVICOS

INTERVALO_VIGIA_S = 10.0
# Recuperação automática tem limite: se um serviço cai sempre, insistir só
# esconde o problema. Depois disso o controller avisa e deixa parado.
MAX_RECUPERACOES = 3

_encerrando = threading.Event()


def _pedir_parada(*_) -> None:
    """Handler de sinal: só marca o evento — parar de dentro dele trava."""
    if not _encerrando.is_set():
        print("\n\nEncerrando… (derrubando os serviços que o Atlas subiu)")
    _encerrando.set()


def _instalar_sinais() -> None:
    signal.signal(signal.SIGINT, _pedir_parada)
    sigterm = getattr(signal, "SIGTERM", None)
    if sigterm is not None:
        try:
            signal.signal(sigterm, _pedir_parada)
        except (ValueError, OSError):
            pass  # nem toda plataforma/thread aceita SIGTERM


def _essenciais() -> list:
    return [s for s in SERVICOS if s.essencial]


def _vigiar() -> None:
    """Laço de supervisão: confere a saúde e recupera quem cair."""
    recuperacoes: dict[str, int] = {}
    desistidos: set[str] = set()

    print(
        f"Controller ativo — vigiando {len(_essenciais())} serviço(s) "
        f"a cada {INTERVALO_VIGIA_S:.0f}s. Ctrl+C para encerrar tudo.\n"
    )

    while not _encerrando.is_set():
        # wait() em vez de sleep(): o Ctrl+C interrompe na hora.
        if _encerrando.wait(timeout=INTERVALO_VIGIA_S):
            break

        for servico in _essenciais():
            if _encerrando.is_set() or servico.nome in desistidos:
                continue
            if gerenciador.esta_no_ar(servico):
                recuperacoes.pop(servico.nome, None)
                continue

            tentativas = recuperacoes.get(servico.nome, 0) + 1
            recuperacoes[servico.nome] = tentativas
            if tentativas > MAX_RECUPERACOES:
                desistidos.add(servico.nome)
                print(
                    f"  [desisto] {servico.nome:<10} caiu {MAX_RECUPERACOES}x seguidas; "
                    f"não vou reerguer. Veja {servico.arquivo_log}"
                )
                continue

            print(
                f"  [caiu]    {servico.nome:<10} fora do ar — recolocando "
                f"({tentativas}/{MAX_RECUPERACOES})"
            )
            gerenciador.iniciar([servico.nome], abrir_navegador=False)


def _iniciar(args) -> int:
    _instalar_sinais()
    codigo = gerenciador.iniciar(
        None,
        baixar_ausentes=args.baixar_modelos,
        abrir_navegador=not args.sem_navegador,
    )
    if codigo != 0:
        print("Um serviço essencial não subiu. Nada a supervisionar — saindo.")
        return codigo

    print(f"  Interface .... http://127.0.0.1:{settings.ui_port}")
    print(f"  API docs ..... http://127.0.0.1:{settings.api_port}/docs\n")

    try:
        _vigiar()
    except KeyboardInterrupt:  # Ctrl+C durante o próprio laço
        _pedir_parada()

    return gerenciador.parar()


def _status(_) -> int:
    return gerenciador.status()


def _parar(args) -> int:
    return gerenciador.parar(incluir_externos=args.tudo)


def _logs(args) -> int:
    caminho = gerenciador.caminho_log(args.servico)
    if not caminho.exists():
        print(f"Sem log ainda para '{args.servico}': {caminho}")
        return 1
    linhas = caminho.read_text(encoding="utf-8", errors="replace").splitlines()
    print("\n".join(linhas[-args.linhas :]))
    return 0


def _saida_utf8() -> None:
    """O console do Windows vem em cp1252 e quebra em acento/símbolo."""
    for fluxo in (sys.stdout, sys.stderr):
        reconfigurar = getattr(fluxo, "reconfigure", None)
        if reconfigurar:
            try:
                reconfigurar(encoding="utf-8")
            except Exception:
                pass


def main() -> int:
    _saida_utf8()
    p = argparse.ArgumentParser(
        prog="app.py",
        description="Atlas — sobe e supervisiona todos os serviços da aplicação.",
    )
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument(
        "--baixar-modelos",
        action="store_true",
        help="baixa no Ollama os modelos do .env que estiverem faltando",
    )
    p.add_argument(
        "--sem-navegador",
        action="store_true",
        help="não abre o navegador depois que tudo subir",
    )
    p.set_defaults(fn=_iniciar)

    sub = p.add_subparsers(dest="comando")
    sub.add_parser("status", help="estado de cada serviço").set_defaults(fn=_status)

    pa = sub.add_parser("parar", help="derruba os serviços que o Atlas subiu")
    pa.add_argument(
        "--tudo",
        action="store_true",
        help="derruba também o Ollama que já rodava antes",
    )
    pa.set_defaults(fn=_parar)

    lo = sub.add_parser("logs", help="mostra o fim do log de um serviço")
    lo.add_argument("servico", choices=[s.nome for s in SERVICOS])
    lo.add_argument("--linhas", type=int, default=40)
    lo.set_defaults(fn=_logs)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
