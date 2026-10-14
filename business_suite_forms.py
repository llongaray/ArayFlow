"""Leitura segura do snapshot de formularios do Meta Business Suite.

Nao executa comandos: produz apenas um plano com UIDs de controles
inequivocos. Nao considera o texto de um post um rotulo de campo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

# Padrao de snapshots do Chrome DevTools MCP, por ex.:
#   uid=2_15 textbox "Legenda" multiline
#   uid=2_16 textbox "Data da publicacao" value="14/10/2026"
_CONTROL = re.compile(r"^\s*(?:[-*]\s*)?uid=(\d+_\d+)\s+([A-Za-z][\w-]*)\b(.*)$")
_LABEL = re.compile(r'"([^"]{1,110})"')

_TEXT_ROLES = frozenset({"textbox", "input", "textarea"})
_DATE_TIME_ROLES = frozenset({"textbox", "input", "textarea", "combobox"})
_UPLOAD_ROLES = frozenset({"button", "input", "file", "generic"})

_CAPTION = re.compile(
    r"^(?:legenda|escreva (?:uma |a )?legenda|adicionar legenda|"
    r"texto da publica[cç][aã]o|caption|write (?:a )?caption|post caption)$", re.I
)
_DATE = re.compile(
    r"^(?:(?:selecionar|escolher) )?(?:data|date)"
    r"(?: (?:de|da|do) (?:agendamento|publica[cç][aã]o|post)|"
    r" (?:programada|de publica[cç][aã]o|to publish|of publication))?$|"
    r"^(?:schedule|scheduled|publish|publication) date$", re.I
)
_TIME = re.compile(
    r"^(?:(?:selecionar|escolher) )?(?:hora|hor[aá]rio|time)"
    r"(?: (?:de|da|do) (?:agendamento|publica[cç][aã]o|post)|"
    r" (?:programado|programada|de publica[cç][aã]o|to publish))?$|"
    r"^(?:schedule|scheduled|publish|publication) time$", re.I
)
_UPLOAD = re.compile(
    r"^(?:adicionar|carregar|enviar|selecionar|escolher|anexar)"
    r" (?:fotos?|imagens?|m[ií]dias?|arquivos?)$|"
    r"^(?:add|upload|select|choose|attach) (?:photos?|images?|media|files?)$|"
    r"^(?:upload|carregar) (?:arquivo|file)$", re.I
)

@dataclass(frozen=True)
class Control:
    uid: str
    role: str
    label: str
    detail: str


def parse_controls(snapshot: str) -> list[Control]:
    controls: list[Control] = []
    for line in snapshot.splitlines():
        match = _CONTROL.match(line)
        if not match:
            continue
        uid, role, details = match.groups()
        name = _LABEL.search(details)
        if name is None:
            continue
        controls.append(Control(uid, role.casefold(), name.group(1).strip(), details))
    return controls


def _unique(controls: Iterable[Control], pattern: re.Pattern[str],
            roles: frozenset[str]) -> tuple[str | None, bool]:
    choices = {
        control.uid for control in controls
        if control.role in roles and pattern.fullmatch(control.label)
    }
    return (next(iter(choices)) if len(choices) == 1 else None, len(choices) > 1)


@dataclass(frozen=True)
class FormFields:
    caption_uid: str | None
    upload_uid: str | None
    date_uid: str | None
    time_uid: str | None
    ambiguous: tuple[str, ...] = ()


def discover_fields(snapshot: str) -> FormFields:
    controls = parse_controls(snapshot)
    caption, cap_amb = _unique(controls, _CAPTION, _TEXT_ROLES)
    upload, upload_amb = _unique(controls, _UPLOAD, _UPLOAD_ROLES)
    date, date_amb = _unique(controls, _DATE, _DATE_TIME_ROLES)
    time, time_amb = _unique(controls, _TIME, _DATE_TIME_ROLES)
    ambiguous = tuple(field for field, is_amb in (
        ("legenda", cap_amb), ("imagens", upload_amb),
        ("data", date_amb), ("horario", time_amb)
    ) if is_amb)
    # Nao preenche somente data ou somente hora: evitar agendamento parcial.
    if date is None or time is None:
        date = time = None
    # Impedir uso do mesmo UID em campos diferentes, mesmo em UI defeituosa.
    if date and len({uid for uid in (date, time, caption) if uid}) != len(
        [uid for uid in (date, time, caption) if uid]
    ):
        date = time = None
    return FormFields(caption, upload, date, time, ambiguous)


def plan_form_values(fields: FormFields, caption: str,
                     when: datetime) -> list[dict[str, str]]:
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("Agendamento exige data/hora com fuso horario")
    if not caption.strip():
        raise ValueError("Legenda vazia")
    values: list[dict[str, str]] = []
    if fields.caption_uid:
        values.append({"uid": fields.caption_uid, "value": caption.strip()})
    if fields.date_uid and fields.time_uid:
        # Locale pt-BR do painel. Se a Meta mostrar outro formato, confira
        # e preencha manualmente; o navegador nao e configurado por esse codigo.
        values.extend([
            {"uid": fields.date_uid, "value": when.strftime("%d/%m/%Y")},
            {"uid": fields.time_uid, "value": when.strftime("%H:%M")},
        ])
    return values


def validate_media_files(files: list[Path]) -> list[str]:
    if not files or len(files) > 10:
        raise ValueError("Quantidade de artes fora do intervalo 1..10")
    paths: list[str] = []
    for file in files:
        path = Path(file)
        if not path.is_file() or path.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
            raise ValueError("Arte inexistente ou formato invalido no disco")
        paths.append(str(path.resolve()))
    return paths


def field_report(fields: FormFields) -> dict[str, bool]:
    return {
        "images": fields.upload_uid is not None,
        "caption": fields.caption_uid is not None,
        "date": fields.date_uid is not None,
        "time": fields.time_uid is not None,
    }
