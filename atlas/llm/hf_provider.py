"""Provedor Hugging Face Transformers — alternativa a Ollama.

Carrega os pesos direto na GPU/CPU. Útil quando você quer controlar
quantização, LoRA ou rodar em servidor sem daemon. Instale antes:
    pip install transformers torch accelerate
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from atlas.config import settings
from atlas.core.types import Mensagem
from atlas.llm.base import ProvedorLLM


class HuggingFaceProvider(ProvedorLLM):
    nome = "huggingface"

    def __init__(self, modelo: str | None = None) -> None:
        self.modelo_id = modelo or settings.text_model
        self._pipe = None

    def _carregar(self):
        if self._pipe is None:
            from transformers import pipeline  # import tardio: dependência pesada

            self._pipe = pipeline(
                "text-generation",
                model=self.modelo_id,
                device_map="auto",
                torch_dtype="auto",
            )
        return self._pipe

    def gerar(self, mensagens: list[Mensagem], modelo: str | None = None, **kw) -> str:
        pipe = self._carregar()
        saida = pipe(
            [m.to_dict() for m in mensagens],
            max_new_tokens=kw.get("max_tokens", settings.max_tokens),
            temperature=kw.get("temperature", settings.temperature),
            do_sample=True,
        )
        return saida[0]["generated_text"][-1]["content"]

    def gerar_stream(
        self, mensagens: list[Mensagem], modelo: str | None = None, **kw
    ) -> Iterator[str]:
        # Streaming real exige TextIteratorStreamer + thread; por ora, uma emissão só.
        yield self.gerar(mensagens, modelo, **kw)

    def ver_imagem(self, prompt: str, imagens: list[Path], modelo: str | None = None) -> str:
        raise NotImplementedError(
            "Visão via Transformers ainda não implementada. "
            "Use o provedor Ollama com um modelo multimodal (qwen2.5vl, llava)."
        )

    def embeddings(self, textos: list[str], modelo: str | None = None) -> list[list[float]]:
        from sentence_transformers import SentenceTransformer

        m = SentenceTransformer(modelo or "sentence-transformers/all-MiniLM-L6-v2")
        return m.encode(textos).tolist()
