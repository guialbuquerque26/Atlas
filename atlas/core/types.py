"""Tipos compartilhados por todo o Atlas.

Este arquivo é o contrato entre os módulos. Um novo analisador
(áudio, planilha, o que for) só precisa devolver um `ResultadoFerramenta`
para entrar no pipeline sem tocar no orquestrador.
"""

from __future__ import annotations

import mimetypes
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

Papel = Literal["system", "user", "assistant"]


class TipoAnexo(str, Enum):
    IMAGEM = "imagem"
    VIDEO = "video"
    DOCUMENTO = "documento"
    AUDIO = "audio"
    DESCONHECIDO = "desconhecido"


EXTENSOES = {
    TipoAnexo.IMAGEM: {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tiff"},
    TipoAnexo.VIDEO: {".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"},
    TipoAnexo.DOCUMENTO: {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".html", ".json"},
    TipoAnexo.AUDIO: {".mp3", ".wav", ".m4a", ".ogg", ".flac"},
}


@dataclass
class Anexo:
    """Arquivo enviado pelo usuário, já classificado."""

    caminho: Path
    tipo: TipoAnexo = TipoAnexo.DESCONHECIDO
    mime: str | None = None

    def __post_init__(self) -> None:
        self.caminho = Path(self.caminho)
        if self.tipo is TipoAnexo.DESCONHECIDO:
            self.tipo = self.classificar(self.caminho)
        if self.mime is None:
            self.mime = mimetypes.guess_type(str(self.caminho))[0]

    @staticmethod
    def classificar(caminho: str | Path) -> TipoAnexo:
        ext = Path(caminho).suffix.lower()
        for tipo, exts in EXTENSOES.items():
            if ext in exts:
                return tipo
        return TipoAnexo.DESCONHECIDO

    @property
    def nome(self) -> str:
        return self.caminho.name


@dataclass
class Mensagem:
    """Turno de conversa."""

    papel: Papel
    conteudo: str
    imagens: list[Path] = field(default_factory=list)
    criada_em: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.papel, "content": self.conteudo}
        if self.imagens:
            d["images"] = [str(p) for p in self.imagens]
        return d


@dataclass
class ResultadoFerramenta:
    """Saída padronizada de qualquer ferramenta/analisador."""

    ferramenta: str
    sucesso: bool
    resumo: str
    dados: dict[str, Any] = field(default_factory=dict)
    fontes: list[str] = field(default_factory=list)
    erro: str | None = None

    def como_contexto(self) -> str:
        cabecalho = f"### [{self.ferramenta}]"
        if not self.sucesso:
            return f"{cabecalho}\nFalhou: {self.erro}"
        corpo = self.resumo
        if self.fontes:
            corpo += "\nFontes: " + "; ".join(self.fontes)
        return f"{cabecalho}\n{corpo}"


@dataclass
class RespostaAtlas:
    """O que o Atlas devolve para a interface."""

    texto: str
    ferramentas_usadas: list[ResultadoFerramenta] = field(default_factory=list)
    fontes: list[str] = field(default_factory=list)
    modelo: str = ""
    duracao_s: float = 0.0
