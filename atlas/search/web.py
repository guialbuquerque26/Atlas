"""Busca na internet sem chave de API.

DuckDuckGo devolve os resultados; trafilatura abre as páginas mais
relevantes e extrai o texto limpo, porque snippet de buscador quase nunca
é suficiente para responder algo com precisão.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from loguru import logger

from atlas.config import settings
from atlas.core.types import ResultadoFerramenta

FERRAMENTA = "busca_na_web"
LIMITE_POR_PAGINA = 4_000
PAGINAS_ABERTAS = 3  # abrir todas custa caro; as primeiras bastam


@dataclass
class Achado:
    titulo: str
    url: str
    trecho: str
    conteudo: str = ""


def _duckduckgo(consulta: str, limite: int) -> list[Achado]:
    from ddgs import DDGS

    with DDGS() as ddgs:
        brutos = list(ddgs.text(consulta, region="br-pt", max_results=limite))
    return [
        Achado(
            titulo=r.get("title", ""),
            url=r.get("href", "") or r.get("url", ""),
            trecho=r.get("body", ""),
        )
        for r in brutos
    ]


PROVEDORES = {"duckduckgo": _duckduckgo}


CABECALHOS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

_cliente = None
_config_trafilatura = None


def _obter_cliente():
    """Cliente HTTP único: reaproveita conexões entre buscas."""
    global _cliente
    if _cliente is None:
        import httpx

        _cliente = httpx.Client(
            headers=CABECALHOS,
            follow_redirects=True,
            timeout=settings.search_timeout_s,
            limits=httpx.Limits(max_connections=PAGINAS_ABERTAS + 2),
        )
    return _cliente


def _obter_config_trafilatura():
    """Config do trafilatura com o nosso timeout — o padrão dele é 30s."""
    global _config_trafilatura
    if _config_trafilatura is None:
        from trafilatura.settings import use_config

        _config_trafilatura = use_config()
        _config_trafilatura.set(
            "DEFAULT", "DOWNLOAD_TIMEOUT", str(int(settings.search_timeout_s))
        )
    return _config_trafilatura


def _baixar(url: str) -> str:
    """Baixa o HTML: httpx primeiro, trafilatura como reserva.

    O httpx é o caminho rápido e reaproveita conexões, mas alguns sites o
    recusam com 403 (o trafilatura passa, com outra pilha HTTP). Sem essa
    reserva perderíamos fontes que antes funcionavam.
    """
    try:
        resposta = _obter_cliente().get(url)
        resposta.raise_for_status()
        return resposta.text
    except Exception as e:
        logger.debug(f"httpx recusado em {url} ({e}); tentando pelo trafilatura")

    import trafilatura

    return trafilatura.fetch_url(url, config=_obter_config_trafilatura()) or ""


def _abrir_pagina(url: str) -> str:
    """Baixa e extrai o texto limpo de uma página."""
    try:
        import trafilatura

        html = _baixar(url)
        if not html:
            return ""
        texto = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
        return texto[:LIMITE_POR_PAGINA]
    except Exception as e:
        logger.debug(f"Não abriu {url}: {e}")
        return ""


def _abrir_paginas(urls: list[str]) -> list[str]:
    """Abre as páginas em paralelo — são chamadas de rede independentes."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=len(urls)) as executor:
        return list(executor.map(_abrir_pagina, urls))


def buscar_na_web(
    consulta: str, max_resultados: int | None = None, abrir_paginas: bool | None = None
) -> ResultadoFerramenta:
    if not settings.search_enabled:
        return ResultadoFerramenta(FERRAMENTA, False, "", erro="Busca desativada na configuração.")

    limite = max_resultados or settings.search_max_results
    abrir = settings.search_fetch_pages if abrir_paginas is None else abrir_paginas
    provedor = PROVEDORES.get(settings.search_provider)
    if provedor is None:
        return ResultadoFerramenta(
            FERRAMENTA, False, "", erro=f"Provedor de busca desconhecido: {settings.search_provider}"
        )

    try:
        achados = provedor(consulta, limite)
    except Exception as e:
        return ResultadoFerramenta(FERRAMENTA, False, "", erro=f"Busca falhou: {e}")

    if not achados:
        return ResultadoFerramenta(
            FERRAMENTA, True, f"Nenhum resultado para: {consulta}", dados={"consulta": consulta}
        )

    if abrir:
        alvos = achados[:PAGINAS_ABERTAS]
        for a, conteudo in zip(alvos, _abrir_paginas([a.url for a in alvos]), strict=False):
            a.conteudo = conteudo

    partes = [f'Resultados para "{consulta}":\n']
    for n, a in enumerate(achados, 1):
        partes.append(f"{n}. {a.titulo}\n   URL: {a.url}\n   {a.trecho}")
        if a.conteudo:
            partes.append(f"   Conteúdo extraído:\n   {a.conteudo}\n")

    return ResultadoFerramenta(
        FERRAMENTA,
        True,
        "\n".join(partes),
        dados={"consulta": consulta, "total": len(achados)},
        fontes=[a.url for a in achados if a.url],
    )
