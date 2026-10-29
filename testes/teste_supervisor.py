"""Testes do supervisor de serviços.

Verificam a coerência das declarações e a lógica de estado — nenhum processo
é iniciado, nenhuma porta é ocupada. Rodam sem Ollama e sem internet.
"""

from pathlib import Path

import pytest

from atlas.config import settings
from atlas.supervisor import definicoes
from atlas.supervisor.definicoes import API, INTERFACE, OLLAMA, SERVICOS, por_nome


def teste_todos_os_servicos_tem_nome_unico():
    nomes = [s.nome for s in SERVICOS]
    assert len(nomes) == len(set(nomes))


def teste_portas_nao_colidem():
    portas = [s.porta for s in SERVICOS]
    assert len(portas) == len(set(portas))


def teste_ollama_sobe_antes_dos_demais():
    """API e interface dependem do servidor de modelos já estar de pé."""
    assert SERVICOS[0] is OLLAMA


def teste_portas_vem_da_configuracao():
    assert API.porta == settings.api_port
    assert INTERFACE.porta == settings.ui_port


def teste_url_de_saude_e_montada_corretamente():
    assert API.url_saude == f"http://127.0.0.1:{settings.api_port}/health"
    assert OLLAMA.url_saude.endswith("/api/tags")


def teste_ollama_e_marcado_como_externo():
    """Externo significa: se já estava rodando, o Atlas não o derruba."""
    assert OLLAMA.externo is True
    assert API.externo is False and INTERFACE.externo is False


def teste_por_nome_encontra_e_recusa():
    assert por_nome("api") is API
    with pytest.raises(KeyError):
        por_nome("inexistente")


def teste_porta_do_host_extrai_o_numero():
    assert definicoes._porta_do_host("http://localhost:11434", 0) == 11434
    assert definicoes._porta_do_host("http://localhost", 11434) == 11434


def teste_diretorio_de_execucao_existe():
    caminho = definicoes.diretorio_execucao()
    assert caminho.exists() and caminho.name == "run"


def teste_logs_ficam_dentro_da_pasta_de_dados():
    for servico in SERVICOS:
        assert Path(settings.logs_dir) in servico.arquivo_log.parents
