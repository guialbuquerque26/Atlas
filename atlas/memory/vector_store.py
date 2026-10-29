"""Memória semântica sobre ChromaDB.

Guarda trechos de documentos e páginas analisadas para que o Atlas possa
recuperá-los em conversas futuras sem reprocessar o arquivo.
"""

from __future__ import annotations

import hashlib
from typing import Any

from loguru import logger

from atlas.config import settings
from atlas.llm import get_llm

COLECAO = "conhecimento_atlas"


class MemoriaVetorial:
    def __init__(self, colecao: str = COLECAO) -> None:
        import chromadb

        self._cliente = chromadb.PersistentClient(path=str(settings.chroma_path))
        self._colecao = self._cliente.get_or_create_collection(
            name=colecao, metadata={"hnsw:space": "cosine"}
        )

    def _vetorizar(self, textos: list[str]) -> list[list[float]]:
        return get_llm().embeddings(textos)

    @staticmethod
    def _id(texto: str) -> str:
        """ID estável pelo conteúdo: reindexar o mesmo trecho não duplica."""
        return hashlib.sha1(texto.encode()).hexdigest()[:16]

    def indexar(self, trechos: list[str], metadados: dict[str, Any] | None = None) -> int:
        """Adiciona trechos com o mesmo metadado para todos."""
        return self.indexar_itens([(t, metadados or {}) for t in trechos])

    def indexar_itens(
        self, itens: list[tuple[str, dict[str, Any]]], lote: int = 128
    ) -> int:
        """Adiciona trechos com metadados por trecho, embutindo em lotes.

        Cada item é (texto, metadados). Embutir em lotes poupa idas ao Ollama
        quando há muitos trechos (ex.: um documento grande). IDs vêm do hash do
        conteúdo, então reindexar não duplica.
        """
        itens = [(t, m) for t, m in itens if t and t.strip()]
        if not itens:
            return 0

        total = 0
        for inicio in range(0, len(itens), lote):
            bloco = itens[inicio : inicio + lote]
            textos = [t for t, _ in bloco]
            try:
                vetores = self._vetorizar(textos)
            except Exception as e:
                logger.warning(f"Embeddings indisponíveis, lote ignorado: {e}")
                continue
            self._colecao.upsert(
                ids=[self._id(t) for t in textos],
                documents=textos,
                embeddings=vetores,
                metadatas=[dict(m) for _, m in bloco],
            )
            total += len(bloco)
        return total

    def buscar(
        self, consulta: str, k: int = 4, filtro: dict[str, Any] | None = None
    ) -> list[dict]:
        if self._colecao.count() == 0:
            return []
        try:
            vetor = self._vetorizar([consulta])[0]
        except Exception as e:
            logger.warning(f"Busca vetorial indisponível: {e}")
            return []

        r = self._colecao.query(
            query_embeddings=[vetor],
            n_results=min(k, self._colecao.count()),
            where=filtro or None,
        )
        saida = []
        for doc, meta, dist in zip(
            r["documents"][0], r["metadatas"][0], r["distances"][0], strict=False
        ):
            saida.append({"texto": doc, "metadados": meta, "similaridade": round(1 - dist, 3)})
        return saida

    def total(self) -> int:
        return self._colecao.count()

    def limpar(self) -> None:
        nome = self._colecao.name
        self._cliente.delete_collection(nome)
        self._colecao = self._cliente.get_or_create_collection(
            name=nome, metadata={"hnsw:space": "cosine"}
        )
