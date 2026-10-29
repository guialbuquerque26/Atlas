"""Escolhe o provedor conforme a configuração."""

from __future__ import annotations

from functools import lru_cache

from atlas.config import settings
from atlas.llm.base import ProvedorLLM

PROVEDORES = {"ollama", "huggingface"}


@lru_cache
def get_llm(provedor: str | None = None) -> ProvedorLLM:
    nome = (provedor or settings.llm_provider).lower()
    if nome == "ollama":
        from atlas.llm.ollama_provider import OllamaProvider

        return OllamaProvider()
    if nome == "huggingface":
        from atlas.llm.hf_provider import HuggingFaceProvider

        return HuggingFaceProvider()
    raise ValueError(f"Provedor desconhecido: {nome}. Opções: {sorted(PROVEDORES)}")
