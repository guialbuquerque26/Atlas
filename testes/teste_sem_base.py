"""Prova que o Atlas funciona sem nenhuma base de conhecimento.

Sem Ollama e sem ChromaDB reais: usa dubles com coleção vazia. O ponto é que
memória vazia / arquivo ausente degrada suave, sem crash.
"""

import pytest

from atlas.core.orchestrator import Atlas
from atlas.documents import buscar_conhecimento
from atlas.memory.vector_store import MemoriaVetorial


class _ColecaoVazia:
    def count(self):
        return 0


def _memoria_vazia() -> MemoriaVetorial:
    mem = MemoriaVetorial.__new__(MemoriaVetorial)  # sem tocar ChromaDB/Ollama
    mem._colecao = _ColecaoVazia()
    return mem


def teste_buscar_em_memoria_vazia_nao_chama_ollama(monkeypatch):
    """count()==0 curto-circuita antes de qualquer embedding."""
    mem = _memoria_vazia()
    mem._vetorizar = lambda _: pytest.fail("não deveria vetorizar com memória vazia")
    assert mem.buscar("qualquer coisa") == []


def teste_buscar_conhecimento_com_memoria_vazia(monkeypatch):
    monkeypatch.setattr("atlas.memory.MemoriaVetorial", _memoria_vazia)
    r = buscar_conhecimento("qualquer coisa")
    assert r.sucesso is True
    assert r.dados["total"] == 0


def teste_montar_contexto_sem_memoria_devolve_vazio():
    """Sem memória (usar_memoria=False), o contexto de um turno sem anexos é vazio."""
    atlas = Atlas.__new__(Atlas)
    atlas.usar_memoria = False
    atlas._vetorial = None
    assert atlas.montar_contexto([], "olá, tudo bem?") == ""


def teste_montar_contexto_com_memoria_vazia_nao_injeta(monkeypatch):
    atlas = Atlas.__new__(Atlas)
    atlas.usar_memoria = True
    atlas._vetorial = _memoria_vazia()
    ctx = atlas.montar_contexto([], "pergunta sem base indexada")
    assert "[memória]" not in ctx
