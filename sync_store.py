"""Sessoes duraveis do ArayFlow. Dados e historico ficam apenas no SQLite local."""
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS daily_syncs (
  day TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  last_error TEXT
);
CREATE TABLE IF NOT EXISTS r2_assets (
  object_key TEXT PRIMARY KEY,
  day TEXT NOT NULL,
  post_id TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS r2_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  day TEXT NOT NULL,
  action TEXT NOT NULL,
  object_key TEXT,
  detail TEXT,
  created_at TEXT NOT NULL
);
"""

def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

class SyncStore:
    def __init__(self, path: Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30)
        self.conn.executescript(DDL)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def begin(self, day: str):
        now = utcnow()
        self.conn.execute(
            """INSERT INTO daily_syncs(day,status,started_at,updated_at,last_error)
               VALUES(?,?,?,?,NULL)
               ON CONFLICT(day) DO UPDATE SET
                 status='running',updated_at=excluded.updated_at,last_error=NULL""",
            (day, "running", now, now))
        self.conn.commit()
        self.event(day, "begin")

    def finish(self, day: str, status: str, error: str = ""):
        if status not in {"complete", "failed"}:
            raise ValueError("Estado de sessao invalido")
        self.conn.execute(
            "UPDATE daily_syncs SET status=?,updated_at=?,last_error=? WHERE day=?",
            (status, utcnow(), error[:300], day))
        self.conn.commit()
        self.event(day, status, detail=error[:300])

    def record_asset(self, day: str, post_id: str, key: str, digest: str):
        self.conn.execute(
            """INSERT INTO r2_assets(object_key,day,post_id,sha256,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(object_key) DO UPDATE SET
                 day=excluded.day, post_id=excluded.post_id,
                 sha256=excluded.sha256, updated_at=excluded.updated_at""",
            (key, day, post_id, digest, utcnow()))
        self.conn.commit()
        self.event(day, "uploaded_or_verified", key)

    def forget_asset(self, day: str, key: str):
        self.conn.execute("DELETE FROM r2_assets WHERE object_key=?", (key,))
        self.conn.commit()
        self.event(day, "deleted", key)

    def event(self, day: str, action: str, key: str | None = None, detail: str = ""):
        self.conn.execute(
            "INSERT INTO r2_events(day,action,object_key,detail,created_at) VALUES(?,?,?,?,?)",
            (day, action, key, detail, utcnow()))
        self.conn.commit()

    def get_sessions(self, limit: int = 15):
        return self.conn.execute(
            """SELECT day,status,updated_at,last_error FROM daily_syncs
               ORDER BY updated_at DESC LIMIT ?""", (limit,)
        ).fetchall()

    def protected_posts(self) -> set[str]:
        """Conteineres Meta podem estar buscando as URLs das imagens."""
        exists = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='publications'"
        ).fetchone()
        if not exists:
            return set()
        rows = self.conn.execute(
            """SELECT post_id FROM publications
               WHERE status IN ('prepared','publishing','uncertain')
                  OR (status='failed' AND container_id IS NOT NULL)"""
        ).fetchall()
        return {row[0] for row in rows}

    def protected_days(self, selected_day: str) -> set[str]:
        """Conserva dias de sessoes incompletas ate retomada/resolucao."""
        return {row[0] for row in self.conn.execute(
            """SELECT day FROM daily_syncs
               WHERE day != ? AND status IN ('running','failed')""",
            (selected_day,)
        ).fetchall()}
