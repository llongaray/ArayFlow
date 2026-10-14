"""Regras do calendário editorial: horário, aprovação e janela de publicação."""
from __future__ import annotations

import re
from datetime import datetime

from google_client import read_calendar

from arayflow.settings import APPROVED, POST_ID_RE, ZONE, sheet_name, spreadsheet_id

PREPARE_MINUTES = 10
MAX_DELAY_MINUTES = 15
_CLOCK = re.compile(r"(\d{1,2}):(\d{2})(?::00)?")


def scheduled_time(row: dict) -> datetime:
    post_id = row.get("ID", "").strip()
    if not POST_ID_RE.fullmatch(post_id):
        raise ValueError("ID editorial invalido")
    day = datetime.strptime(row.get("Data", "").strip(), "%d/%m/%Y").date()
    if post_id[5:13] != day.strftime("%Y%m%d"):
        raise ValueError(f"ID/data divergentes em {post_id}")
    hour = row.get("Horário", "").strip()
    match = _CLOCK.fullmatch(hour)
    if not match or int(match[1]) > 23 or int(match[2]) > 59:
        raise ValueError(f"Horario invalido em {post_id}: {hour}")
    return datetime(
        day.year, day.month, day.day, int(match[1]), int(match[2]), tzinfo=ZONE,
    )


def decision(row: dict, now: datetime) -> str:
    """SKIP, WAIT, PREPARE, DUE ou EXPIRED. Posts muito atrasados não são recuperados."""
    if row.get("Status", "").strip().casefold() not in APPROVED:
        return "SKIP"
    due = scheduled_time(row)
    delta = (due - now.astimezone(ZONE)).total_seconds()
    if delta > PREPARE_MINUTES * 60:
        return "WAIT"
    if delta < -MAX_DELAY_MINUTES * 60:
        return "EXPIRED"
    return "DUE" if delta <= 0 else "PREPARE"


def load_sheet_rows(sheets) -> list[dict]:
    return read_calendar(sheets, spreadsheet_id(), sheet_name())


def rows_on_date(rows: list[dict], sheet_date: str) -> list[dict]:
    """Filtra linhas de um dia (dd/mm/aaaa) e recusa IDs repetidos."""
    selected = [row for row in rows if row.get("Data", "").strip() == sheet_date]
    ids = [row.get("ID", "").strip() for row in selected]
    if len(ids) != len(set(ids)):
        raise ValueError("IDs duplicados no calendario; operacao cancelada")
    return selected


def rows_today(sheets, now: datetime) -> list[dict]:
    rows = load_sheet_rows(sheets)
    date = now.astimezone(ZONE).strftime("%d/%m/%Y")
    return rows_on_date(rows, date)
