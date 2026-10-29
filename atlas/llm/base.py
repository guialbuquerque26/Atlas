"""Contrato do provedor de LLM.

Trocar Ollama por vLLM, llama.cpp ou Transformers = escrever uma classe
que implemente estes quatro métodos. Nenhum outro módulo muda.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path

from atlas.core.types import Mensagem


class ProvedorLLM(ABC):
    nome: str = "base"

    @abstractmethod
    def gerar(self, mensagens: list[Mensagem], modelo: str | None = None, **kw) -> str:
        """Resposta completa em uma chamada."""

    @abstractmethod
    def gerar_stream(
        self, mensagens: list[Mensagem], modelo: str | None = None, **kw
    ) -> Iterator[str]:
        """Resposta token a token."""

    @abstractmethod
    def ver_imagem(self, prompt: str, imagens: list[Path], modelo: str | None = None) -> str:
        """Consulta multimodal: prompt + uma ou mais imagens."""

    @abstractmethod
    def embeddings(self, textos: list[str], modelo: str | None = None) -> list[list[float]]:
        """Vetores para memória semântica."""

    def disponivel(self) -> bool:
        """Checagem de saúde. Sobrescreva quando fizer sentido."""
        return True
