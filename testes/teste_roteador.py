"""Testes do atalho de decisão de busca.

Rodam sem Ollama e sem internet — a heurística é pura.
"""

import pytest

from atlas.core.roteador import decidir_rapido, normalizar


@pytest.mark.parametrize(
    "pergunta",
    [
        "Olá, tudo bem?",
        "bom dia",
        "Obrigado!",
        "Escreva uma função Python que inverte uma string",
        "Corrija este bug no meu código",
        "Traduza 'good morning' para o português",
        "Me explique o que é recursão em programação.",
    ],
)
def teste_conversa_e_codigo_nao_buscam(pergunta):
    assert decidir_rapido(pergunta) is False


@pytest.mark.parametrize(
    "pergunta",
    [
        "Qual o preço do dólar hoje?",
        "Cotação do bitcoin agora",
        "Qual a última versão do Python?",
        "Quem venceu a eleição?",
        "Qual a previsão do tempo para amanhã?",
        "Notícias sobre inteligência artificial",
    ],
)
def teste_informacao_que_muda_com_o_tempo_busca(pergunta):
    assert decidir_rapido(pergunta) is True


@pytest.mark.parametrize(
    "pergunta",
    [
        "Como funciona um motor de combustão?",
        "Qual a capital da Austrália?",
        "Quantos habitantes tem o Japão?",
    ],
)
def teste_zona_cinzenta_delega_ao_modelo(pergunta):
    assert decidir_rapido(pergunta) is None


def teste_sinal_temporal_vence_sinal_de_conversa():
    """'explique' sozinho não busca, mas com 'última versão' passa a buscar."""
    assert decidir_rapido("Explique como usar o Python") is False
    assert decidir_rapido("Explique a última versão do Python") is True


def teste_pergunta_vazia_nao_busca():
    assert decidir_rapido("") is False
    assert decidir_rapido("   ") is False


def teste_acento_nao_muda_a_decisao():
    assert decidir_rapido("qual o preço do dólar hoje") is True
    assert decidir_rapido("qual o preco do dolar hoje") is True


def teste_normalizar_remove_acentos_e_caixa():
    assert normalizar("Cotação DO Dólar") == "cotacao do dolar"
