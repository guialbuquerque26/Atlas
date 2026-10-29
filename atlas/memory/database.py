"""Histórico de conversas em SQLite. Zero dependência externa."""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from atlas.config import settings
from atlas.core.types import Mensagem

ESQUEMA = """
CREATE TABLE IF NOT EXISTS sessoes (
    id          TEXT PRIMARY KEY,
    titulo      TEXT,
    criada_em   TEXT NOT NULL,
    atualizada_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mensagens (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sessao_id   TEXT NOT NULL REFERENCES sessoes(id) ON DELETE CASCADE,
    papel       TEXT NOT NULL,
    conteudo    TEXT NOT NULL,
    anexos      TEXT DEFAULT '[]',
    ferramentas TEXT DEFAULT '[]',
    criada_em   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mensagens_sessao ON mensagens(sessao_id, id);
"""


class Banco:
    def __init__(self, caminho: Path | None = None) -> None:
        self.caminho = caminho or settings.sqlite_path
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        with self._conectar() as c:
            c.executescript(ESQUEMA)

    @contextmanager
    def _conectar(self):
        # timeout > 0 faz o SQLite esperar o lock em vez de estourar na hora;
        # WAL deixa leitura e escrita concorrerem — sem isso, vários usuários
        # simultâneos batem em "database is locked".
        con = sqlite3.connect(self.caminho, timeout=10.0)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = NORMAL")
        con.execute("PRAGMA busy_timeout = 10000")
        try:
            yield con
            con.commit()
        finally:
            con.close()

    # ------------------------------------------------------------- sessões
    def criar_sessao(self, titulo: str = "Nova conversa") -> str:
        sid = uuid.uuid4().hex[:12]
        agora = datetime.now().isoformat(timespec="seconds")
        with self._conectar() as c:
            c.execute(
                "INSERT INTO sessoes (id, titulo, criada_em, atualizada_em) VALUES (?,?,?,?)",
                (sid, titulo, agora, agora),
            )
        return sid

    def listar_sessoes(self, limite: int = 50) -> list[dict]:
        with self._conectar() as c:
            linhas = c.execute(
                "SELECT * FROM sessoes ORDER BY atualizada_em DESC LIMIT ?", (limite,)
            ).fetchall()
        return [dict(l) for l in linhas]

    def apagar_sessao(self, sessao_id: str) -> None:
        with self._conectar() as c:
            c.execute("DELETE FROM sessoes WHERE id = ?", (sessao_id,))

    # ----------------------------------------------------------- mensagens
    def salvar_mensagem(
        self,
        sessao_id: str,
        mensagem: Mensagem,
        anexos: list[str] | None = None,
        ferramentas: list[str] | None = None,
    ) -> None:
        agora = datetime.now().isoformat(timespec="seconds")
        with self._conectar() as c:
            c.execute(
                "INSERT INTO mensagens (sessao_id, papel, conteudo, anexos, ferramentas, criada_em)"
                " VALUES (?,?,?,?,?,?)",
                (
                    sessao_id,
                    mensagem.papel,
                    mensagem.conteudo,
                    json.dumps(anexos or [], ensure_ascii=False),
                    json.dumps(ferramentas or [], ensure_ascii=False),
                    agora,
                ),
            )
            c.execute("UPDATE sessoes SET atualizada_em = ? WHERE id = ?", (agora, sessao_id))

    def historico(self, sessao_id: str, limite: int = 20) -> list[Mensagem]:
        with self._conectar() as c:
            linhas = c.execute(
                "SELECT papel, conteudo FROM mensagens WHERE sessao_id = ?"
                " ORDER BY id DESC LIMIT ?",
                (sessao_id, limite),
            ).fetchall()
        return [Mensagem(l["papel"], l["conteudo"]) for l in reversed(linhas)]
