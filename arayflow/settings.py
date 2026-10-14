"""Caminhos, fuso e identificadores usados por todos os comandos."""
from __future__ import annotations

import os
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

try:
    ZONE = ZoneInfo("America/Sao_Paulo")
except Exception as exc:
    raise RuntimeError(
        "Instale tzdata (`py -m pip install tzdata`) para usar o fuso America/Sao_Paulo."
    ) from exc
POST_ID_RE = re.compile(r"ARAY-\d{8}-\d{3,}$")
APPROVED = frozenset({
    "aprovado",
    "aprovado para publicação",
    "aprovado para publicacao",
})
DB_PATH = BASE_DIR / "data" / "arayflow.sqlite3"
CHROME_PROFILE_DIR = BASE_DIR / "data" / "playwright_chrome_profile"

DEFAULT_SPREADSHEET_ID = "1dA5GFM2qS6RXzpgEiBXLHO4uYkwp4l46B17dCZCcZKM"
DEFAULT_SHEET_NAME = "Calendário"
DEFAULT_GOOGLE_EMAIL = "aray.solucoes@gmail.com"


def spreadsheet_id() -> str:
    return os.getenv("GOOGLE_SPREADSHEET_ID", DEFAULT_SPREADSHEET_ID).strip()


def sheet_name() -> str:
    return os.getenv("GOOGLE_SHEET_NAME", DEFAULT_SHEET_NAME).strip()


def spreadsheet_url() -> str:
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id()}/edit"


def google_email() -> str:
    return os.getenv("GOOGLE_ACCOUNT_EMAIL", DEFAULT_GOOGLE_EMAIL).strip().lower()


def autopublish_enabled() -> bool:
    return os.getenv("ARAYFLOW_AUTOPUBLISH_ENABLED", "").strip().lower() == "true"
