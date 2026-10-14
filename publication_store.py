"""Estado local, idempotencia e trilha de publicacao em SQLite."""
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS publications (
  post_id TEXT PRIMARY KEY,
  status TEXT NOT NULL,
  media_id TEXT,
  container_id TEXT,
  updated_at TEXT NOT NULL
);
"""
class PublicationStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.execute(SCHEMA)
        self.conn.commit()

    def get(self, post_id: str):
        return self.conn.execute(
            "SELECT status, media_id, container_id FROM publications WHERE post_id=?",
            (post_id,)
        ).fetchone()

    def set(self, post_id: str, status: str, *, media_id=None, container_id=None):
        if status not in {"prepared", "publishing", "published", "uncertain", "failed"}:
            raise ValueError("Status invalido")
        self.conn.execute(
            """INSERT INTO publications(post_id,status,media_id,container_id,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(post_id) DO UPDATE SET
               status=excluded.status,
               media_id=COALESCE(excluded.media_id, publications.media_id),
               container_id=COALESCE(excluded.container_id, publications.container_id),
               updated_at=excluded.updated_at""",
            (post_id, status, media_id, container_id,
             datetime.now(timezone.utc).isoformat())
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
