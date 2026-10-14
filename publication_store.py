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
        if status not in {"preparing", "prepared", "publishing", "published", "uncertain", "failed"}:
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

    def claim(self, post_id: str) -> bool:
        """Reserva atomicamente um post nunca processado; bloqueia repeticoes."""
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            # Impede colisao com posts preparados no Business Suite.
            table = self.conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='business_suite_schedule'"
            ).fetchone()
            if table and self.conn.execute(
                "SELECT 1 FROM business_suite_schedule WHERE post_id=?", (post_id,)
            ).fetchone():
                self.conn.rollback()
                return False
            cur = self.conn.execute(
                """INSERT OR IGNORE INTO publications
                   (post_id,status,media_id,container_id,updated_at)
                   VALUES(?,'preparing',NULL,NULL,?)""", (post_id, now)
            )
            self.conn.commit()
            return cur.rowcount == 1
        except Exception:
            self.conn.rollback()
            raise

    def transition(self, post_id: str, expected: str, target: str,
                   *, media_id=None, container_id=None) -> bool:
        """Atualiza apenas se a sessao estiver no estado esperado."""
        if target not in {"preparing","prepared","publishing","published","uncertain","failed"}:
            raise ValueError("Status invalido")
        cur = self.conn.execute(
            """UPDATE publications SET status=?,
               media_id=COALESCE(?,media_id),
               container_id=COALESCE(?,container_id),updated_at=?
               WHERE post_id=? AND status=?""",
            (target, media_id, container_id,
             datetime.now(timezone.utc).isoformat(), post_id, expected)
        )
        self.conn.commit()
        return cur.rowcount == 1

    def business_suite_reserved(self, post_id: str) -> bool:
        """Detecta agendamento assistido antes de qualquer media_publish automatica."""
        exists = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='business_suite_schedule'"
        ).fetchone()
        if not exists:
            return False
        return self.conn.execute(
            "SELECT 1 FROM business_suite_schedule WHERE post_id=?",
            (post_id,)
        ).fetchone() is not None
