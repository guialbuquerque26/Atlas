"""Controle de admissão das chamadas ao modelo.

A GPU serializa a inferência: um 7B atende ~uma requisição por vez. Sem limite,
20 usuários simultâneos viram uma fila de 60s+ na qual todo mundo espera e os
clientes expiram — pior que recusar cedo.

Aqui só existe um semáforo: quem consegue vaga executa, quem não consegue em
`admissao_timeout_s` recebe `SistemaOcupado`, que a API traduz em 503 com
`Retry-After`. Falhar rápido e explicitamente é melhor que pendurar.
"""

from __future__ import annotations

import threading
from contextlib import contextmanager

from atlas.config import settings


class SistemaOcupado(RuntimeError):
    """Não havia vaga de inferência dentro do tempo tolerado."""


_semaforo = threading.BoundedSemaphore(max(1, settings.max_inferencias))


@contextmanager
def vaga_de_inferencia(timeout: float | None = None):
    """Segura uma vaga durante a chamada ao modelo, ou recusa."""
    espera = settings.admissao_timeout_s if timeout is None else timeout
    if not _semaforo.acquire(timeout=espera):
        raise SistemaOcupado(
            "Todas as vagas de inferência estão ocupadas. Tente novamente em instantes."
        )
    try:
        yield
    finally:
        _semaforo.release()


def vagas_livres() -> int:
    """Aproximação para diagnóstico (o valor interno não é público)."""
    return getattr(_semaforo, "_value", 0)
