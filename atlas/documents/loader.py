"""Leitura de documentos. Um extrator por formato, registrados por extensão.

Para suportar um novo formato, escreva a função e adicione ao dicionário
EXTRATORES no fim do arquivo. Nada mais precisa mudar.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Callable

from atlas.core.types import ResultadoFerramenta

FERRAMENTA = "leitura_de_documento"
LIMITE_CONTEXTO = 12_000  # caracteres injetados direto no prompt


# ------------------------------------------------------------------ extratores
def _txt(caminho: Path) -> str:
    return caminho.read_text(encoding="utf-8", errors="replace")


def _pdf(caminho: Path) -> str:
    from pypdf import PdfReader

    leitor = PdfReader(str(caminho))
    partes = []
    for n, pagina in enumerate(leitor.pages, 1):
        texto = (pagina.extract_text() or "").strip()
        if texto:
            partes.append(f"--- Página {n} ---\n{texto}")
    if not partes:
        return "[PDF sem camada de texto — provavelmente digitalizado. Requer OCR.]"
    return "\n\n".join(partes)


def _docx(caminho: Path) -> str:
    import docx

    doc = docx.Document(str(caminho))
    linhas = [p.text for p in doc.paragraphs if p.text.strip()]
    for tabela in doc.tables:
        for linha in tabela.rows:
            linhas.append(" | ".join(c.text.strip() for c in linha.cells))
    return "\n".join(linhas)


def _xlsx(caminho: Path) -> str:
    from openpyxl import load_workbook

    wb = load_workbook(str(caminho), data_only=True)
    partes = []
    for aba in wb.worksheets:
        partes.append(f"--- Planilha: {aba.title} ---")
        for linha in aba.iter_rows(values_only=True):
            if any(c is not None for c in linha):
                partes.append(" | ".join("" if c is None else str(c) for c in linha))
    return "\n".join(partes)


def _csv(caminho: Path) -> str:
    bruto = caminho.read_text(encoding="utf-8", errors="replace")
    try:
        dialeto = csv.Sniffer().sniff(bruto[:2048])
    except csv.Error:
        dialeto = csv.excel
    linhas = list(csv.reader(io.StringIO(bruto), dialeto))
    return "\n".join(" | ".join(l) for l in linhas)


def _html(caminho: Path) -> str:
    from bs4 import BeautifulSoup

    sopa = BeautifulSoup(caminho.read_text(encoding="utf-8", errors="replace"), "lxml")
    for tag in sopa(["script", "style", "nav", "footer"]):
        tag.decompose()
    return sopa.get_text("\n", strip=True)


def _json(caminho: Path) -> str:
    dados = json.loads(caminho.read_text(encoding="utf-8", errors="replace"))
    return json.dumps(dados, ensure_ascii=False, indent=2)


EXTRATORES: dict[str, Callable[[Path], str]] = {
    ".txt": _txt,
    ".md": _txt,
    ".pdf": _pdf,
    ".docx": _docx,
    ".xlsx": _xlsx,
    ".csv": _csv,
    ".html": _html,
    ".htm": _html,
    ".json": _json,
}


# ---------------------------------------------------------------------- API
def carregar_documento(caminho: str | Path) -> ResultadoFerramenta:
    caminho = Path(caminho)
    if not caminho.exists():
        return ResultadoFerramenta(FERRAMENTA, False, "", erro=f"Arquivo não encontrado: {caminho}")

    extrator = EXTRATORES.get(caminho.suffix.lower())
    if extrator is None:
        return ResultadoFerramenta(
            FERRAMENTA, False, "", erro=f"Formato não suportado: {caminho.suffix}"
        )

    try:
        texto = extrator(caminho).strip()
    except Exception as e:
        return ResultadoFerramenta(FERRAMENTA, False, "", erro=f"Falha ao extrair texto: {e}")

    palavras = len(texto.split())
    corpo = texto[:LIMITE_CONTEXTO]
    if len(texto) > LIMITE_CONTEXTO:
        corpo += f"\n\n[... truncado: {len(texto) - LIMITE_CONTEXTO} caracteres restantes ...]"

    resumo = f"Documento `{caminho.name}` ({palavras} palavras):\n\n{corpo}"
    return ResultadoFerramenta(
        FERRAMENTA,
        True,
        resumo,
        dados={
            "arquivo": caminho.name,
            "caracteres": len(texto),
            "palavras": palavras,
            "texto_completo": texto,
        },
    )


def dividir_em_trechos(texto: str, tamanho: int = 1200, sobreposicao: int = 200) -> list[str]:
    """Fatia texto para indexação vetorial, quebrando em fronteiras de parágrafo."""
    if len(texto) <= tamanho:
        return [texto] if texto.strip() else []

    sobreposicao = min(sobreposicao, tamanho // 2)  # evita laço infinito
    trechos, inicio = [], 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            corte = texto.rfind("\n\n", inicio, fim)
            if corte == -1:
                corte = texto.rfind(". ", inicio, fim)
            if corte > inicio + tamanho // 2:
                fim = corte + 1
        pedaco = texto[inicio:fim].strip()
        if pedaco:
            trechos.append(pedaco)
        if fim >= len(texto):
            break
        inicio = fim - sobreposicao
    return trechos
