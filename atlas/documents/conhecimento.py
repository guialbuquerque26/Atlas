"""Busca semântica na base de conhecimento indexada na memória vetorial."""

from __future__ import annotations

from atlas.core.types import ResultadoFerramenta

FERRAMENTA = "buscar_conhecimento"


def buscar_conhecimento(
    consulta: str, fonte: str | None = None, k: int = 5
) -> ResultadoFerramenta:
    """Busca semântica na base de conhecimento indexada (documentos e anotações).

    `fonte` restringe a uma origem; vazio busca em tudo.
    """
    from atlas.memory import MemoriaVetorial

    filtro = {"fonte": fonte} if fonte else None
    try:
        achados = MemoriaVetorial().buscar(consulta, k=k, filtro=filtro)
    except Exception as e:
        return ResultadoFerramenta(FERRAMENTA, False, "", erro=f"Busca no conhecimento falhou: {e}")

    relevantes = [a for a in achados if a["similaridade"] > 0.3]
    if not relevantes:
        return ResultadoFerramenta(
            FERRAMENTA, True, f"Nada relevante encontrado para: {consulta}",
            dados={"consulta": consulta, "total": 0},
        )

    partes = [f'Conhecimento para "{consulta}":\n']
    fontes: list[str] = []
    for n, a in enumerate(relevantes, 1):
        titulo = a["metadados"].get("titulo") or a["metadados"].get("ferramenta", "sem título")
        partes.append(f"{n}. [{titulo}] (similaridade {a['similaridade']:.0%})\n   {a['texto']}")
        if titulo not in fontes:
            fontes.append(titulo)

    return ResultadoFerramenta(
        FERRAMENTA,
        True,
        "\n".join(partes),
        dados={"consulta": consulta, "total": len(relevantes)},
        fontes=fontes,
    )
