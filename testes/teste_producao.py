"""Testes do endurecimento para produção.

Sem Ollama e sem rede: exercitam classificação de erro, retry, admissão,
limite de sessões e os PRAGMAs do SQLite.
"""

import threading
import time

import httpx
import pytest

from atlas.config import settings
from atlas.core.admissao import SistemaOcupado
from atlas.llm.ollama_provider import OllamaIndisponivel, OllamaProvider
from atlas.memory import Banco


# ------------------------------------------------------------ classificação
@pytest.mark.parametrize(
    "erro,transitorio",
    [
        (httpx.ConnectError("recusado"), True),
        (httpx.ReadError("caiu"), True),
        (httpx.TimeoutException("demorou"), True),
        (ValueError("bug nosso"), False),
    ],
)
def teste_classifica_erro_transitorio(erro, transitorio):
    assert OllamaProvider._transitorio(erro) is transitorio


def teste_status_5xx_e_transitorio_4xx_nao():
    def _erro(codigo):
        resp = httpx.Response(codigo, request=httpx.Request("POST", "http://x"))
        return httpx.HTTPStatusError("x", request=resp.request, response=resp)

    assert OllamaProvider._transitorio(_erro(503)) is True
    assert OllamaProvider._transitorio(_erro(400)) is False


def _provedor(cliente) -> OllamaProvider:
    """Provedor sem __init__ (nada de rede), com o disjuntor zerado."""
    p = OllamaProvider.__new__(OllamaProvider)
    p.host = "http://x"
    p._cliente = cliente
    p._falhas = 0
    p._aberto_ate = 0.0
    p._trava = threading.Lock()
    return p


def teste_post_desiste_e_levanta_indisponivel(monkeypatch):
    """Erro transitório persistente vira OllamaIndisponivel, não trava."""
    monkeypatch.setattr(settings, "ollama_tentativas", 2)
    monkeypatch.setattr(settings, "ollama_backoff_s", 0.001)
    monkeypatch.setattr(settings, "ollama_circuito_falhas", 99)  # isola do disjuntor
    chamadas = []

    class ClienteFalho:
        def post(self, *a, **kw):
            chamadas.append(1)
            raise httpx.ConnectError("recusado")

    with pytest.raises(OllamaIndisponivel):
        _provedor(ClienteFalho())._post("/api/chat", {})
    assert len(chamadas) == 2  # respeitou o teto de tentativas


def teste_post_nao_retenta_erro_do_cliente(monkeypatch):
    """4xx é problema nosso: repetir não ajuda e mascara o bug."""
    monkeypatch.setattr(settings, "ollama_tentativas", 3)
    chamadas = []

    class Cliente400:
        def post(self, *a, **kw):
            chamadas.append(1)
            resp = httpx.Response(400, request=httpx.Request("POST", "http://x"))
            raise httpx.HTTPStatusError("ruim", request=resp.request, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        _provedor(Cliente400())._post("/api/chat", {})
    assert len(chamadas) == 1


def teste_post_recupera_apos_falha_transitoria(monkeypatch):
    monkeypatch.setattr(settings, "ollama_tentativas", 3)
    monkeypatch.setattr(settings, "ollama_backoff_s", 0.001)
    monkeypatch.setattr(settings, "ollama_circuito_falhas", 99)
    estado = {"n": 0}

    class ClienteInstavel:
        def post(self, *a, **kw):
            estado["n"] += 1
            if estado["n"] == 1:
                raise httpx.ConnectError("primeira falha")
            return httpx.Response(200, json={"ok": True}, request=httpx.Request("POST", "http://x"))

    assert _provedor(ClienteInstavel())._post("/api/chat", {}).json() == {"ok": True}
    assert estado["n"] == 2


# --------------------------------------------------------------- disjuntor
def _provedor_falho(monkeypatch) -> OllamaProvider:
    monkeypatch.setattr(settings, "ollama_tentativas", 1)
    monkeypatch.setattr(settings, "ollama_backoff_s", 0.001)
    monkeypatch.setattr(settings, "ollama_circuito_falhas", 2)
    monkeypatch.setattr(settings, "ollama_circuito_pausa_s", 30.0)

    p = OllamaProvider.__new__(OllamaProvider)
    p.host = "http://127.0.0.1:1"
    p._falhas = 0
    p._aberto_ate = 0.0
    p._trava = threading.Lock()
    p.tentativas_http = 0

    class ClienteFalho:
        def post(self, *a, **kw):
            p.tentativas_http += 1
            raise httpx.ConnectError("recusado")

    p._cliente = ClienteFalho()
    return p


def teste_disjuntor_abre_e_falha_na_hora(monkeypatch):
    """Depois do limite, nem tenta a rede — falha instantânea."""
    p = _provedor_falho(monkeypatch)

    for _ in range(2):  # atinge o limite de falhas
        with pytest.raises(OllamaIndisponivel):
            p._post("/api/chat", {})
    assert p.tentativas_http == 2

    t = time.perf_counter()
    with pytest.raises(OllamaIndisponivel, match="disjuntor aberto"):
        p._post("/api/chat", {})
    assert time.perf_counter() - t < 0.05  # não tocou a rede
    assert p.tentativas_http == 2  # confirma: nenhuma tentativa nova


def teste_disjuntor_fecha_apos_a_pausa(monkeypatch):
    p = _provedor_falho(monkeypatch)
    for _ in range(2):
        with pytest.raises(OllamaIndisponivel):
            p._post("/api/chat", {})

    p._aberto_ate = 0.0  # simula o fim da pausa
    with pytest.raises(OllamaIndisponivel):
        p._post("/api/chat", {})
    assert p.tentativas_http == 3  # voltou a tentar


def teste_sucesso_fecha_o_disjuntor(monkeypatch):
    p = _provedor_falho(monkeypatch)
    with pytest.raises(OllamaIndisponivel):
        p._post("/api/chat", {})
    assert p._falhas == 1

    class ClienteBom:
        def post(self, *a, **kw):
            return httpx.Response(200, json={}, request=httpx.Request("POST", "http://x"))

    p._cliente = ClienteBom()
    p._post("/api/chat", {})
    assert p._falhas == 0 and p._aberto_ate == 0.0


# ---------------------------------------------------------------- admissão
def teste_admissao_recusa_quando_saturado(monkeypatch):
    """Sem vaga dentro do tempo, recusa em vez de enfileirar sem limite."""
    import atlas.core.admissao as adm

    monkeypatch.setattr(adm, "_semaforo", threading.BoundedSemaphore(1))
    monkeypatch.setattr(settings, "admissao_timeout_s", 0.05)

    with adm.vaga_de_inferencia():  # ocupa a única vaga
        t = time.perf_counter()
        with pytest.raises(SistemaOcupado):
            with adm.vaga_de_inferencia():
                pass
        assert time.perf_counter() - t < 1.0  # recusou rápido


def teste_admissao_libera_a_vaga_apos_uso(monkeypatch):
    import atlas.core.admissao as adm

    monkeypatch.setattr(adm, "_semaforo", threading.BoundedSemaphore(1))
    with adm.vaga_de_inferencia():
        pass
    with adm.vaga_de_inferencia():  # a vaga voltou
        pass


def teste_admissao_devolve_vaga_mesmo_com_excecao(monkeypatch):
    import atlas.core.admissao as adm

    monkeypatch.setattr(adm, "_semaforo", threading.BoundedSemaphore(1))
    with pytest.raises(ValueError):
        with adm.vaga_de_inferencia():
            raise ValueError("falhou no meio")
    with adm.vaga_de_inferencia():  # não vazou
        pass


# ------------------------------------------------------------------ SQLite
def teste_banco_usa_wal(tmp_path):
    banco = Banco(tmp_path / "teste.sqlite3")
    with banco._conectar() as con:
        modo = con.execute("PRAGMA journal_mode").fetchone()[0]
    assert modo.lower() == "wal"


def teste_banco_escreve_de_varias_threads(tmp_path):
    """WAL + busy_timeout: escrita concorrente não estoura 'database is locked'."""
    from atlas.core.types import Mensagem

    banco = Banco(tmp_path / "concorrente.sqlite3")
    sessao = banco.criar_sessao()
    erros: list[Exception] = []

    def escrever(n):
        try:
            for i in range(5):
                banco.salvar_mensagem(sessao, Mensagem("user", f"t{n}-{i}"))
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    threads = [threading.Thread(target=escrever, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not erros, f"escrita concorrente falhou: {erros[:2]}"
    assert len(banco.historico(sessao, limite=100)) == 40


# -------------------------------------------------------------------- jobs
def teste_job_conclui_e_guarda_resultado():
    from atlas.api.jobs import criar_job, obter_job

    job = criar_job(lambda x: {"valor": x * 2}, 21)
    for _ in range(50):
        if obter_job(job.id).estado != "executando":
            break
        time.sleep(0.02)
    concluido = obter_job(job.id)
    assert concluido.estado == "concluido"
    assert concluido.resultado == {"valor": 42}
    assert concluido.concluido_em is not None


def teste_job_que_falha_vira_estado_e_nao_derruba():
    from atlas.api.jobs import criar_job, obter_job

    def quebra():
        raise RuntimeError("falha proposital")

    job = criar_job(quebra)
    for _ in range(50):
        if obter_job(job.id).estado != "executando":
            break
        time.sleep(0.02)
    falho = obter_job(job.id)
    assert falho.estado == "falhou"
    assert "falha proposital" in falho.erro


def teste_job_inexistente():
    from atlas.api.jobs import obter_job

    assert obter_job("nao-existe") is None


# ------------------------------------------------------- sessões da API
def teste_sessoes_respeitam_o_limite(monkeypatch):
    """O cache de sessões não pode crescer sem parar (o histórico é durável)."""
    import atlas.api.server as srv

    monkeypatch.setattr(settings, "max_sessoes_memoria", 3)
    monkeypatch.setattr(srv, "_sessoes", type(srv._sessoes)())

    class AtlasFake:
        def __init__(self, sessao_id=None):
            self.sessao_id = sessao_id or f"s{len(srv._sessoes)}"

    monkeypatch.setattr(srv, "Atlas", AtlasFake)
    for _ in range(10):
        srv._atlas(None)
    assert len(srv._sessoes) == 3
