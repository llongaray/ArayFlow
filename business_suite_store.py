"""Registro local dos agendamentos criados manualmente no Meta Business Suite.

Marca 'scheduled' SOMENTE apos confirmacao humana no navegador. A integracao
Meta Graph API consulta estas reservas para nao publicar o mesmo post novamente.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from arayflow.store import SqliteResource

SCHEMA = """
CREATE TABLE IF NOT EXISTS business_suite_schedule (
  post_id TEXT PRIMARY KEY,
  target_at TEXT NOT NULL,
  status TEXT NOT NULL,
  note TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

class BusinessSuiteStore(SqliteResource):
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def get(self, post_id: str):
        row = self.conn.execute(
            "SELECT post_id,target_at,status,note,updated_at FROM business_suite_schedule WHERE post_id=?",
            (post_id,)
        ).fetchone()
        return dict(zip(("post_id", "target_at", "status", "note", "updated_at"), row)) if row else None

    def all(self, limit: int = 100):
        rows = self.conn.execute(
            """SELECT post_id,target_at,status,note,updated_at
               FROM business_suite_schedule ORDER BY target_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(zip(("post_id", "target_at", "status", "note", "updated_at"), row)) for row in rows]

    def reserved(self, post_id: str) -> bool:
        return self.get(post_id) is not None

    def reserve(self, post_id: str, target_at: str) -> bool:
        """Reserva post em transacao: impede corrida com o publicador da API."""
        now = utcnow()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            # Se existe registro Meta via API, o post nao pode ser duplicado.
            exists = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publications'"
            ).fetchone()
            if exists and self.conn.execute(
                "SELECT 1 FROM publications WHERE post_id=?", (post_id,)
            ).fetchone():
                self.conn.rollback()
                return False
            inserted = self.conn.execute(
                """INSERT OR IGNORE INTO business_suite_schedule
                   (post_id,target_at,status,note,created_at,updated_at)
                   VALUES(?,?,'awaiting_confirmation',NULL,?,?)""",
                (post_id, target_at, now, now)
            ).rowcount == 1
            self.conn.commit()
            return inserted
        except Exception:
            self.conn.rollback()
            raise

    def update(self, post_id: str, expected: str, status: str, note: str = "") -> bool:
        if status not in {"scheduled", "needs_review"}:
            raise ValueError("Status invalido")
        result = self.conn.execute(
            """UPDATE business_suite_schedule SET status=?, note=?, updated_at=?
               WHERE post_id=? AND status=?""",
            (status, note[:250], utcnow(), post_id, expected)
        )
        self.conn.commit()
        return result.rowcount == 1
