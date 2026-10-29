"""Configuração central do Atlas.

Todos os módulos leem daqui. Nada de constante espalhada pelo código:
para mudar o modelo, o provedor ou os limites, edite o `.env`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

RAIZ = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=RAIZ / ".env",
        env_prefix="ATLAS_",
        extra="ignore",
        protected_namespaces=(),
    )

    # ---- LLM ----
    llm_provider: str = "ollama"
    # 127.0.0.1 e não "localhost" de propósito: no Windows, "localhost" resolve
    # primeiro para ::1 (IPv6) e o Ollama só escuta em IPv4 — a primeira conexão
    # de cada processo esperava ~2s no timeout do IPv6 antes de cair no IPv4.
    ollama_host: str = "http://127.0.0.1:11434"
    # Quanto tempo o Ollama segura o modelo na memória depois da última chamada.
    # O padrão (5min) deixa o modelo de embeddings expirar entre turnos espaçados;
    # recarregar custa segundos. Não reserva VRAM: o Ollama despeja quando precisa.
    ollama_keep_alive: str = "30m"
    text_model: str = "qwen2.5:7b-instruct"
    vision_model: str = "qwen2.5vl:7b"
    embed_model: str = "nomic-embed-text"

    # ---- Geração ----
    temperature: float = 0.4
    max_tokens: int = 2048
    context_window: int = 8192

    # ---- Memória (RAG) ----
    # Corte de similaridade para injetar uma lembrança no contexto. Calibrado para
    # o nomic-embed-text: fora de domínio bate ~0.60-0.68, relevante ~0.72+.
    memoria_limiar_similaridade: float = 0.70
    memoria_max_chars: int = 1000  # por lembrança injetada
    memoria_k: int = 5  # trechos recuperados por turno antes do corte de similaridade

    # ---- Busca ----
    search_enabled: bool = True
    search_provider: str = "duckduckgo"
    search_max_results: int = 5
    search_fetch_pages: bool = True
    search_timeout_s: float = 8.0  # teto por página; sem isso uma lenta trava o turno

    # ---- Vídeo ----
    video_max_frames: int = 12
    video_scene_threshold: float = 12.0
    video_lote_frames: int = 4  # frames por chamada ao modelo de visão

    # ---- Servidor ----
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    ui_port: int = 7860
    ui_abrir_navegador: bool = True

    # ---- Produção ----
    # A GPU serializa a inferência: mais chamadas em voo só engordam a fila. Ao
    # saturar, a API responde 503 com Retry-After em vez de enfileirar sem limite.
    max_inferencias: int = 2
    admissao_timeout_s: float = 2.0  # espera por uma vaga antes de recusar
    # Retry de erros transitórios do Ollama (conexão recusada, 5xx).
    ollama_tentativas: int = 3
    ollama_backoff_s: float = 0.5
    # Disjuntor: após N falhas seguidas, as chamadas falham na hora por uma
    # pausa, em vez de cada requisição gastar o ciclo inteiro de tentativas.
    ollama_circuito_falhas: int = 3
    ollama_circuito_pausa_s: float = 20.0
    # Timeouts por operação (o antigo era 300s para tudo).
    ollama_timeout_texto_s: float = 120.0
    ollama_timeout_visao_s: float = 300.0
    ollama_timeout_embed_s: float = 60.0
    # Sessões vivas em memória na API (o histórico é durável no SQLite).
    max_sessoes_memoria: int = 200
    # Segurança
    cors_origins: str = ""  # vazio = nenhuma origem externa; use vírgula p/ separar
    api_token: str = ""  # vazio = sem autenticação (só para uso local)
    upload_max_mb: float = 50.0

    # ---- Diretórios ----
    data_dir: Path = Field(default=RAIZ / "data")

    @property
    def uploads_dir(self) -> Path:
        return self._garantir(self.data_dir / "uploads")

    @property
    def db_dir(self) -> Path:
        return self._garantir(self.data_dir / "db")

    @property
    def logs_dir(self) -> Path:
        return self._garantir(self.data_dir / "logs")

    @property
    def sqlite_path(self) -> Path:
        return self.db_dir / "atlas.sqlite3"

    @property
    def chroma_path(self) -> Path:
        return self._garantir(self.db_dir / "chroma")

    @staticmethod
    def _garantir(caminho: Path) -> Path:
        caminho.mkdir(parents=True, exist_ok=True)
        return caminho


@lru_cache
def get_settings() -> Settings:
    """Instância única de configuração (cacheada)."""
    return Settings()


settings = get_settings()
