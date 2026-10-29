"""Catálogo dos serviços que compõem o Atlas em execução.

Cada serviço é declarado uma única vez aqui — comando, porta e como provar
que está de pé. O gerenciador não sabe nada específico sobre Ollama, API ou
interface: ele só lê esta lista. Para acrescentar um serviço novo (áudio,
worker de indexação), basta adicionar um `Servico` em `SERVICOS`.
"""

from __future__ import annotations

import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from atlas.config import settings


@dataclass(frozen=True)
class Servico:
    """Descrição declarativa de um processo do Atlas."""

    nome: str
    descricao: str
    comando: list[str]
    porta: int
    caminho_saude: str = "/"
    # Serviço essencial: se não subir, o conjunto é considerado quebrado.
    essencial: bool = True
    # Segundos de tolerância até o serviço responder ao healthcheck.
    espera_s: int = 90
    # Serviço externo ao projeto: se já estiver no ar, é adotado, nunca derrubado.
    externo: bool = False
    variaveis_ambiente: dict[str, str] = field(default_factory=dict)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.porta}"

    @property
    def url_saude(self) -> str:
        return f"{self.url}{self.caminho_saude}"

    @property
    def arquivo_log(self) -> Path:
        return settings.logs_dir / f"{self.nome}.log"

    @property
    def arquivo_pid(self) -> Path:
        return diretorio_execucao() / f"{self.nome}.json"

    def disponivel_no_sistema(self) -> bool:
        """O executável do comando existe nesta máquina?"""
        return shutil.which(self.comando[0]) is not None or Path(self.comando[0]).exists()


def diretorio_execucao() -> Path:
    """Pasta de estado volátil: PIDs dos processos em execução."""
    caminho = settings.data_dir / "run"
    caminho.mkdir(parents=True, exist_ok=True)
    return caminho


def _executavel_ollama() -> str:
    """Ollama no PATH, ou no caminho padrão de instalação do Windows."""
    encontrado = shutil.which("ollama")
    if encontrado:
        return encontrado
    padrao = Path.home() / "AppData/Local/Programs/Ollama/ollama.exe"
    return str(padrao) if padrao.exists() else "ollama"


def _porta_do_host(host: str, padrao: int) -> int:
    """Extrai a porta de `ATLAS_OLLAMA_HOST` (http://localhost:11434)."""
    try:
        return int(host.rstrip("/").rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return padrao


OLLAMA = Servico(
    nome="ollama",
    descricao="Servidor de modelos (texto, visão e embeddings)",
    comando=[_executavel_ollama(), "serve"],
    porta=_porta_do_host(settings.ollama_host, 11434),
    caminho_saude="/api/tags",
    espera_s=60,
    externo=True,
)

API = Servico(
    nome="api",
    descricao="API REST (FastAPI) — documentação em /docs",
    comando=[sys.executable, "-m", "atlas.api.server"],
    porta=settings.api_port,
    caminho_saude="/health",
    espera_s=120,
)

INTERFACE = Servico(
    nome="interface",
    descricao="Interface web (Gradio)",
    comando=[sys.executable, "-m", "atlas.ui.app"],
    porta=settings.ui_port,
    caminho_saude="/",
    espera_s=120,
    # Quem abre o navegador é o supervisor, uma vez só, depois que tudo subiu.
    variaveis_ambiente={"ATLAS_UI_ABRIR_NAVEGADOR": "false"},
)

# A ordem importa: o Ollama precisa estar de pé antes de API e interface.
SERVICOS: list[Servico] = [OLLAMA, API, INTERFACE]

MODELOS_NECESSARIOS: list[tuple[str, str]] = [
    ("texto", settings.text_model),
    ("visão", settings.vision_model),
    ("embeddings", settings.embed_model),
]


def por_nome(nome: str) -> Servico:
    for servico in SERVICOS:
        if servico.nome == nome:
            return servico
    disponiveis = ", ".join(s.nome for s in SERVICOS)
    raise KeyError(f"Serviço desconhecido: {nome}. Disponíveis: {disponiveis}")
