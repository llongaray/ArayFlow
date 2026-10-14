"""Preenchimento experimental e supervisionado de data/hora no Meta Suite.

Somente usa tres inputs unicos: campo de data text/date, hora (0-23)
e minuto (0-59). Nunca aciona Publicar, Programar ou Agendar.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/Sao_Paulo")
_PT_MONTHS = (
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
)
_ALLOWED = {
    "verified", "unsupported", "ambiguous", "not-scheduled",
    "invalid-format", "not-visible", "rejected", "wrong-host",
}


def schedule_fill_js(when: datetime) -> str:
    """Gera script JS com APENAS data/hora validadas; nao inclui legenda."""
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("Data/hora sem fuso")
    local = when.astimezone(ZONE)
    if local <= datetime.now(ZONE):
        raise ValueError("Data/hora ja passou")
    values = {
        "day": local.day, "month": local.month, "year": local.year,
        "hour": local.hour, "minute": local.minute,
        "pt": f"{local.day} de {_PT_MONTHS[local.month - 1]} de {local.year}",
        "br": f"{local.day:02d}/{local.month:02d}/{local.year}",
        "iso": local.strftime("%Y-%m-%d"),
    }
    js_values = json.dumps(values, ensure_ascii=True)
    return _FILL_TEMPLATE.replace("__ARAYFLOW_TARGET__", js_values)


def interpret_schedule_fill(mcp_text: str) -> tuple[bool, str]:
    """Nao imprime retorno bruto do browser; so enum de status permitido."""
    decoder = json.JSONDecoder()
    payload = None
    for item in re.finditer(r"\{", mcp_text):
        try:
            value, _ = decoder.raw_decode(mcp_text[item.start():])
        except ValueError:
            continue
        if isinstance(value, dict) and value.get("marker") == "arayflow-schedule-v1":
            payload = value
            break
    if not payload:
        return False, "unreadable"
    status = payload.get("status")
    if status not in _ALLOWED:
        return False, "unknown"
    return status == "verified", status


_FILL_TEMPLATE = r"""async () => {
  const target = __ARAYFLOW_TARGET__;
  const response = status => ({marker: "arayflow-schedule-v1", status});
  if (location.hostname !== "business.facebook.com" ||
      !location.pathname.startsWith("/latest/composer")) return response("wrong-host");
  const body = document.body?.innerText || "";
  if (!body.includes("Definir data e hora") ||
      !body.includes("Programar") ||
      !body.includes("Adicionar foto/vídeo")) return response("not-scheduled");

  const visible = e => {
    const rect = e.getBoundingClientRect();
    const style = getComputedStyle(e);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== "none" && style.visibility !== "hidden" &&
           !e.disabled && !e.readOnly && e.getAttribute("aria-readonly") !== "true";
  };
  const inputs = [...document.querySelectorAll("input")].filter(visible);
  const norm = s => (s || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const label = e => [
    e.getAttribute("aria-label"), e.getAttribute("placeholder"),
    e.getAttribute("title"), e.getAttribute("name"),
    ...(e.labels ? [...e.labels].map(x => x.textContent) : [])
  ].filter(Boolean).map(norm).join(" ");
  const range = e => {
    const low = e.getAttribute("aria-valuemin") ?? e.getAttribute("min");
    const high = e.getAttribute("aria-valuemax") ?? e.getAttribute("max");
    return (low != null && high != null) ? (low + "-" + high) : "";
  };
  const candidates = {
    date: inputs.filter(e =>
      ["text", "date"].includes((e.type || "text").toLowerCase()) &&
      (/\b(data|date)\b/.test(label(e))) &&
      !/\b(nascimento|birth)\b/.test(label(e))),
    hour: inputs.filter(e => e.getAttribute("role") === "spinbutton" && range(e) === "0-23"),
    minute: inputs.filter(e => e.getAttribute("role") === "spinbutton" && range(e) === "0-59"),
  };
  if (Object.values(candidates).some(list => list.length !== 1)) {
    return response("ambiguous");
  }
  const [date, hour, minute] = [
    candidates.date[0], candidates.hour[0], candidates.minute[0]
  ];
  if (new Set([date, hour, minute]).size !== 3) return response("ambiguous");

  const before = date.value.trim().toLowerCase();
  const dateAsIso = date.type === "date";
  let newDate = null;
  if (dateAsIso || /^\d{4}-\d{2}-\d{2}$/.test(before)) newDate = target.iso;
  else if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(before)) newDate = target.br;
  else if (/^\d{1,2} de [a-zà-úç]+ de \d{4}$/.test(before)) newDate = target.pt;
  if (!newDate) return response("invalid-format");
  if (hour.type !== "text" || minute.type !== "text") {
    return response("unsupported");
  }
  if (!/^\d{1,2}$/.test(hour.value) || !/^\d{1,2}$/.test(minute.value)) {
    return response("invalid-format");
  }
  const next = [
    [date, newDate], [hour, String(target.hour).padStart(2, "0")],
    [minute, String(target.minute).padStart(2, "0")]
  ];
  const setNative = (e, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    if (!setter) return false;
    setter.call(e, value);
    e.dispatchEvent(new Event("input", {bubbles: true}));
    e.dispatchEvent(new Event("change", {bubbles: true}));
    e.dispatchEvent(new Event("blur", {bubbles: true}));
    return true;
  };
  try {
    for (const [el, value] of next) {
      if (!setNative(el, value)) return response("unsupported");
    }
    await new Promise(resolve => setTimeout(resolve, 600));
    const same = (el, value) =>
      document.contains(el) && el.value.trim().toLowerCase() === value.toLowerCase();
    if (!next.every(([el, value]) => same(el, value))) {
      return response("rejected");
    }
    return response("verified");
  } catch (_) {
    return response("rejected");
  }
}"""
