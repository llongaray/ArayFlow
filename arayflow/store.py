"""Abre e fecha os registros SQLite no mesmo padrão."""
from __future__ import annotations


class SqliteResource:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        close = getattr(self, "close", None)
        if close is not None:
            close()
        return False
