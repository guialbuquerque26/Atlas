"""Análise de imagens: metadados objetivos + leitura semântica pelo modelo de visão."""

from __future__ import annotations

from pathlib import Path

from loguru import logger
from PIL import Image

from atlas.core.prompts import DESCREVER_IMAGEM
from atlas.core.types import ResultadoFerramenta
from atlas.llm import get_llm

FERRAMENTA = "analise_de_imagem"


def metadados(caminho: Path) -> dict:
    """Fatos que não dependem de modelo nenhum."""
    with Image.open(caminho) as img:
        largura, altura = img.size
        modo = img.mode
        formato = img.format
        cores = _cores_dominantes(img)
    return {
        "arquivo": caminho.name,
        "largura": largura,
        "altura": altura,
        "proporcao": round(largura / altura, 3) if altura else None,
        "modo": modo,
        "formato": formato,
        "cores_dominantes": cores,
        "tamanho_kb": round(caminho.stat().st_size / 1024, 1),
    }


def _cores_dominantes(img: Image.Image, n: int = 5) -> list[str]:
    pequena = img.convert("RGB").resize((64, 64))
    paleta = pequena.quantize(colors=n, method=Image.Quantize.FASTOCTREE)
    tabela = paleta.getpalette()[: n * 3]
    return ["#%02x%02x%02x" % tuple(tabela[i : i + 3]) for i in range(0, len(tabela), 3)]


def analisar_imagem(caminho: str | Path, pergunta: str | None = None) -> ResultadoFerramenta:
    """Descreve uma imagem. Se `pergunta` vier, responde sobre ela em vez de descrever."""
    caminho = Path(caminho)
    if not caminho.exists():
        return ResultadoFerramenta(FERRAMENTA, False, "", erro=f"Arquivo não encontrado: {caminho}")

    try:
        meta = metadados(caminho)
    except Exception as e:  # imagem corrompida, formato exótico
        return ResultadoFerramenta(FERRAMENTA, False, "", erro=f"Não foi possível abrir: {e}")

    prompt = pergunta or DESCREVER_IMAGEM
    try:
        descricao = get_llm().ver_imagem(prompt, [caminho])
    except Exception as e:
        logger.error(f"Modelo de visão falhou em {caminho.name}: {e}")
        return ResultadoFerramenta(
            FERRAMENTA,
            False,
            "",
            dados=meta,
            erro=f"Modelo de visão indisponível ({e}). Verifique se o Ollama está rodando "
            "e se o modelo multimodal foi baixado.",
        )

    resumo = (
        f"Imagem `{meta['arquivo']}` ({meta['largura']}x{meta['altura']}, {meta['formato']}).\n"
        f"{descricao}"
    )
    meta["descricao"] = descricao
    return ResultadoFerramenta(FERRAMENTA, True, resumo, dados=meta)
