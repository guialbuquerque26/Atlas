"""Testes de fundação: garantem que a arquitetura está de pé.

Rodam sem Ollama, sem internet e sem modelos baixados.
"""

from pathlib import Path

import pytest

from atlas.config import settings
from atlas.core.types import Anexo, Mensagem, ResultadoFerramenta, TipoAnexo
from atlas.documents.loader import dividir_em_trechos
from atlas.tools import registro


def teste_configuracao_cria_diretorios():
    assert settings.uploads_dir.exists()
    assert settings.db_dir.exists()


@pytest.mark.parametrize(
    "nome,esperado",
    [
        ("foto.jpg", TipoAnexo.IMAGEM),
        ("clipe.MP4", TipoAnexo.VIDEO),
        ("contrato.pdf", TipoAnexo.DOCUMENTO),
        ("nota.mp3", TipoAnexo.AUDIO),
        ("binario.xyz", TipoAnexo.DESCONHECIDO),
    ],
)
def teste_classificacao_de_anexos(nome, esperado):
    assert Anexo.classificar(nome) is esperado


def teste_mensagem_serializa_para_o_formato_do_llm():
    m = Mensagem("user", "olá", imagens=[Path("a.png")])
    d = m.to_dict()
    assert d["role"] == "user" and d["content"] == "olá" and d["images"] == ["a.png"]


def teste_resultado_falho_expoe_o_erro_no_contexto():
    r = ResultadoFerramenta("teste", False, "", erro="sem conexão")
    assert "sem conexão" in r.como_contexto()


def teste_divisao_respeita_o_limite():
    texto = "\n\n".join(f"Parágrafo {i}. " + "palavra " * 60 for i in range(12))
    trechos = dividir_em_trechos(texto, tamanho=800, sobreposicao=100)
    assert len(trechos) > 1
    assert all(len(t) <= 1000 for t in trechos)


def teste_ferramentas_padrao_registradas():
    assert {"analisar_imagem", "analisar_video", "ler_documento", "buscar_na_web"} <= set(registro)


def teste_schema_de_ferramenta_e_valido():
    schema = registro["analisar_imagem"].como_schema()
    assert schema["function"]["name"] == "analisar_imagem"
    assert "caminho" in schema["function"]["parameters"]["required"]
