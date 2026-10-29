"""Registro de ferramentas.

Uma ferramenta é qualquer função que devolva `ResultadoFerramenta`.
Decore com @registrar e ela passa a existir para o orquestrador, para a API
e para futuras chamadas de função pelo modelo — sem editar mais nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from atlas.core.types import ResultadoFerramenta


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    funcao: Callable[..., ResultadoFerramenta]
    parametros: dict = field(default_factory=dict)

    def __call__(self, *a, **kw) -> ResultadoFerramenta:
        return self.funcao(*a, **kw)

    def como_schema(self) -> dict:
        """Formato compatível com function calling (OpenAI/Ollama tools)."""
        return {
            "type": "function",
            "function": {
                "name": self.nome,
                "description": self.descricao,
                "parameters": {
                    "type": "object",
                    "properties": self.parametros,
                    "required": [k for k, v in self.parametros.items() if v.get("required")],
                },
            },
        }


registro: dict[str, Ferramenta] = {}


def registrar(nome: str, descricao: str, parametros: dict | None = None):
    def decorador(fn: Callable[..., ResultadoFerramenta]):
        registro[nome] = Ferramenta(nome, descricao, fn, parametros or {})
        return fn

    return decorador


def carregar_padrao() -> None:
    """Registra as ferramentas nativas do Atlas."""
    from atlas.documents import buscar_conhecimento, carregar_documento
    from atlas.search import buscar_na_web
    from atlas.vision import analisar_imagem, analisar_video

    registrar(
        "analisar_imagem",
        "Descreve e interpreta uma imagem: cena, objetos, pessoas, texto e cores.",
        {"caminho": {"type": "string", "description": "Caminho do arquivo", "required": True},
         "pergunta": {"type": "string", "description": "Pergunta específica sobre a imagem"}},
    )(analisar_imagem)

    registrar(
        "analisar_video",
        "Analisa um vídeo por frames-chave: objetos, pessoas, cenas e eventos ao longo do tempo.",
        {"caminho": {"type": "string", "description": "Caminho do arquivo", "required": True},
         "pergunta": {"type": "string", "description": "Pergunta específica sobre o vídeo"}},
    )(analisar_video)

    registrar(
        "ler_documento",
        "Extrai o texto de PDF, DOCX, XLSX, CSV, HTML, JSON, TXT ou Markdown.",
        {"caminho": {"type": "string", "description": "Caminho do arquivo", "required": True}},
    )(carregar_documento)

    registrar(
        "buscar_na_web",
        "Pesquisa na internet e extrai o conteúdo das páginas mais relevantes.",
        {"consulta": {"type": "string", "description": "Termos de busca", "required": True}},
    )(buscar_na_web)

    registrar(
        "buscar_conhecimento",
        "Busca na base de conhecimento indexada (documentos analisados e anotações) "
        "por trechos relevantes a uma consulta.",
        {"consulta": {"type": "string", "description": "O que procurar", "required": True}},
    )(buscar_conhecimento)


carregar_padrao()
