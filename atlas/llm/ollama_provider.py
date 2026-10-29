"""Provedor Ollama — o caminho padrão do Atlas.

Por que Ollama: roda modelos abertos (Qwen, Llama, Mistral, Gemma) em
Windows sem compilar nada, expõe texto, visão e embeddings na mesma API
e não exige chave.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
from loguru import logger

from atlas.config import settings
from atlas.core.admissao import vaga_de_inferencia
from atlas.core.types import Mensagem
from atlas.llm.base import ProvedorLLM


class OllamaIndisponivel(RuntimeError):
    """O servidor de modelos não respondeu depois das tentativas previstas."""


class OllamaProvider(ProvedorLLM):
    nome = "ollama"

    def __init__(self, host: str | None = None) -> None:
        self.host = (host or settings.ollama_host).rstrip("/")
        self._cliente = httpx.Client(
            base_url=self.host, timeout=settings.ollama_timeout_texto_s
        )
        # Disjuntor: conta falhas seguidas e abre para não repetir o ciclo de
        # tentativas em toda requisição enquanto o servidor está fora.
        self._falhas = 0
        self._aberto_ate = 0.0
        self._trava = threading.Lock()

    # -------------------------------------------------------------- disjuntor
    def _circuito_aberto(self) -> bool:
        with self._trava:
            return time.monotonic() < self._aberto_ate

    def _registrar_falha(self) -> None:
        with self._trava:
            self._falhas += 1
            if self._falhas >= settings.ollama_circuito_falhas:
                self._aberto_ate = time.monotonic() + settings.ollama_circuito_pausa_s
                logger.warning(
                    f"Disjuntor aberto por {settings.ollama_circuito_pausa_s:.0f}s "
                    f"após {self._falhas} falhas seguidas do Ollama."
                )

    def _registrar_sucesso(self) -> None:
        with self._trava:
            if self._falhas:
                logger.info("Ollama respondeu; disjuntor fechado.")
            self._falhas = 0
            self._aberto_ate = 0.0

    def _barrar_se_aberto(self) -> None:
        if self._circuito_aberto():
            raise OllamaIndisponivel(
                f"Servidor de modelos fora do ar em {self.host} "
                "(disjuntor aberto). Tente novamente em instantes."
            )

    # ------------------------------------------------------------------ util
    def _opcoes(self, **kw) -> dict:
        return {
            "temperature": kw.get("temperature", settings.temperature),
            "num_predict": kw.get("max_tokens", settings.max_tokens),
            "num_ctx": kw.get("context_window", settings.context_window),
        }

    @staticmethod
    def _transitorio(e: Exception) -> bool:
        """Vale retentar? Conexão recusada/queda e 5xx sim; 4xx não."""
        if isinstance(e, (httpx.ConnectError, httpx.ReadError, httpx.WriteError)):
            return True
        if isinstance(e, httpx.TimeoutException):
            return True
        if isinstance(e, httpx.HTTPStatusError):
            return e.response.status_code >= 500
        return False

    def _post(self, rota: str, payload: dict, timeout: float | None = None) -> httpx.Response:
        """POST com backoff exponencial e jitter nos erros transitórios.

        O Ollama é um processo à parte: reiniciar, trocar de modelo ou ficar sem
        VRAM derruba conexões por alguns segundos. Sem retry, uma queda momentânea
        vira falha em cascata (aconteceu: 559 operações perdidas de uma vez).
        """
        self._barrar_se_aberto()
        ultimo: Exception | None = None
        for tentativa in range(1, max(1, settings.ollama_tentativas) + 1):
            try:
                r = self._cliente.post(rota, json=payload, timeout=timeout)
                r.raise_for_status()
                self._registrar_sucesso()
                return r
            except Exception as e:  # noqa: BLE001 — reclassificado abaixo
                ultimo = e
                if not self._transitorio(e) or tentativa == settings.ollama_tentativas:
                    break
                espera = settings.ollama_backoff_s * (2 ** (tentativa - 1))
                espera += random.uniform(0, settings.ollama_backoff_s)
                logger.warning(
                    f"Ollama falhou ({type(e).__name__}), tentativa "
                    f"{tentativa}/{settings.ollama_tentativas}; nova em {espera:.1f}s"
                )
                time.sleep(espera)

        if isinstance(ultimo, httpx.HTTPStatusError) and ultimo.response.status_code < 500:
            raise ultimo  # erro do nosso lado: não mascarar
        self._registrar_falha()
        raise OllamaIndisponivel(
            f"Servidor de modelos indisponível em {self.host} após "
            f"{settings.ollama_tentativas} tentativa(s). Verifique se o Ollama está no ar."
        ) from ultimo

    def disponivel(self) -> bool:
        try:
            return self._cliente.get("/api/tags", timeout=5.0).status_code == 200
        except httpx.HTTPError:
            return False

    def modelos_instalados(self) -> list[str]:
        try:
            r = self._cliente.get("/api/tags", timeout=10.0)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError as e:
            logger.warning(f"Não foi possível listar modelos: {e}")
            return []

    # ----------------------------------------------------------------- texto
    def gerar(self, mensagens: list[Mensagem], modelo: str | None = None, **kw) -> str:
        payload = {
            "model": modelo or settings.text_model,
            "messages": [m.to_dict() for m in mensagens],
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "options": self._opcoes(**kw),
        }
        with vaga_de_inferencia():
            r = self._post("/api/chat", payload, timeout=settings.ollama_timeout_texto_s)
        return r.json()["message"]["content"]

    def gerar_stream(
        self, mensagens: list[Mensagem], modelo: str | None = None, **kw
    ) -> Iterator[str]:
        """Emite token a token.

        Só dá para retentar enquanto nenhum token saiu: depois que o cliente já
        recebeu texto, repetir duplicaria a resposta. Por isso o retry cobre a
        abertura do stream, e a partir do primeiro token o erro sobe.
        """
        payload = {
            "model": modelo or settings.text_model,
            "messages": [m.to_dict() for m in mensagens],
            "stream": True,
            "keep_alive": settings.ollama_keep_alive,
            "options": self._opcoes(**kw),
        }

        with vaga_de_inferencia():  # a vaga fica presa enquanto o stream vive
            yield from self._stream_com_retry(payload)

    def _stream_com_retry(self, payload: dict) -> Iterator[str]:
        import json

        self._barrar_se_aberto()
        ultimo: Exception | None = None
        for tentativa in range(1, max(1, settings.ollama_tentativas) + 1):
            emitiu = False
            try:
                with self._cliente.stream(
                    "POST", "/api/chat", json=payload,
                    timeout=settings.ollama_timeout_texto_s,
                ) as r:
                    r.raise_for_status()
                    self._registrar_sucesso()
                    for linha in r.iter_lines():
                        if not linha:
                            continue
                        bloco = json.loads(linha)
                        if pedaco := bloco.get("message", {}).get("content"):
                            emitiu = True
                            yield pedaco
                        if bloco.get("done"):
                            return
                return
            except Exception as e:  # noqa: BLE001 — reclassificado abaixo
                ultimo = e
                if emitiu or not self._transitorio(e):
                    raise
                if tentativa == settings.ollama_tentativas:
                    break
                espera = settings.ollama_backoff_s * (2 ** (tentativa - 1))
                espera += random.uniform(0, settings.ollama_backoff_s)
                logger.warning(
                    f"Stream do Ollama falhou antes do 1º token "
                    f"({type(e).__name__}); nova tentativa em {espera:.1f}s"
                )
                time.sleep(espera)

        self._registrar_falha()
        raise OllamaIndisponivel(
            f"Servidor de modelos indisponível em {self.host} após "
            f"{settings.ollama_tentativas} tentativa(s)."
        ) from ultimo

    # ----------------------------------------------------------------- visão
    def ver_imagem(self, prompt: str, imagens: list[Path], modelo: str | None = None) -> str:
        import base64

        b64 = [base64.b64encode(Path(p).read_bytes()).decode() for p in imagens]
        payload = {
            "model": modelo or settings.vision_model,
            "messages": [{"role": "user", "content": prompt, "images": b64}],
            "stream": False,
            "keep_alive": settings.ollama_keep_alive,
            "options": self._opcoes(),
        }
        with vaga_de_inferencia():
            r = self._post("/api/chat", payload, timeout=settings.ollama_timeout_visao_s)
        return r.json()["message"]["content"]

    # ------------------------------------------------------------ embeddings
    def embeddings(self, textos: list[str], modelo: str | None = None) -> list[list[float]]:
        payload = {
            "model": modelo or settings.embed_model,
            "input": textos,
            "keep_alive": settings.ollama_keep_alive,
        }
        with vaga_de_inferencia():
            r = self._post("/api/embed", payload, timeout=settings.ollama_timeout_embed_s)
        return r.json()["embeddings"]
