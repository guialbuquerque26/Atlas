"""Trabalhos longos fora do ciclo da requisição.

Analisar um vídeo leva minutos: manter a conexão HTTP aberta esse tempo todo
desperdiça thread, esbarra em timeout de proxy e, se o cliente desiste, o
trabalho continua sem ninguém para receber o resultado.

Aqui o pedido vira um job: a rota devolve 202 com um id e o cliente consulta
quando quiser. Registro em memória e limitado — para 5-20 usuários internos é
suficiente; acima disso, o caminho é uma fila externa (Celery/RQ).
"""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from loguru import logger

from atlas.config import settings

Estado = Literal["executando", "concluido", "falhou"]
MAX_JOBS = 500  # histórico recente; os mais antigos saem


@dataclass
class Job:
    id: str
    estado: Estado = "executando"
    criado_em: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    concluido_em: str | None = None
    resultado: dict[str, Any] | None = None
    erro: str | None = None

    def como_dict(self) -> dict:
        return {
            "job_id": self.id,
            "estado": self.estado,
            "criado_em": self.criado_em,
            "concluido_em": self.concluido_em,
            "resultado": self.resultado,
            "erro": self.erro,
        }


_jobs: OrderedDict[str, Job] = OrderedDict()
_trava = threading.Lock()
# Mesmo teto da admissão: quem executa é a GPU, não adianta ter mais threads.
_executor = ThreadPoolExecutor(
    max_workers=max(1, settings.max_inferencias), thread_name_prefix="atlas-job"
)


def criar_job(funcao: Callable[..., dict], *args, **kwargs) -> Job:
    """Agenda a função e devolve o job já registrado como 'executando'."""
    job = Job(id=uuid.uuid4().hex[:12])
    with _trava:
        _jobs[job.id] = job
        while len(_jobs) > MAX_JOBS:
            _jobs.popitem(last=False)

    def _executar() -> None:
        try:
            resultado = funcao(*args, **kwargs)
            job.resultado = resultado
            job.estado = "concluido"
        except Exception as e:  # noqa: BLE001 — o erro vira estado do job
            logger.warning(f"Job {job.id} falhou: {e}")
            job.erro = str(e)
            job.estado = "falhou"
        finally:
            job.concluido_em = datetime.now().isoformat(timespec="seconds")

    _executor.submit(_executar)
    return job


def obter_job(job_id: str) -> Job | None:
    with _trava:
        return _jobs.get(job_id)


def total_jobs() -> int:
    with _trava:
        return len(_jobs)
