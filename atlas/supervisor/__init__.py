"""Supervisão dos processos que o Atlas precisa para funcionar.

Ollama, API e interface sobem em conjunto, na ordem certa, com healthcheck.
Uso pela linha de comando: `python -m atlas.supervisor iniciar`.
"""

from atlas.supervisor.definicoes import SERVICOS, Servico, por_nome

__all__ = ["SERVICOS", "Servico", "por_nome"]
