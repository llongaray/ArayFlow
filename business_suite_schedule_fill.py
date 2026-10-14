"""Preenchimento experimental e supervisionado de data/hora no Meta Suite.

Liga o interruptor "Definir data e hora" quando ele esta desligado.
Depois grava a data e a hora:minuto em controles unicos do compositor.
Nunca aciona Publicar, Programar ou Agendar.
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
      !body.includes("Programar")) return response("not-scheduled");

  const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
  const norm = s => (s || "")
    .replace(/[\u00a0\u202f\u2007\u2009\u200b\ufeff]/g, " ")
    .normalize("NFD").replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+/g, " ").trim().toLowerCase();
  const shown = e => {
    const rect = e.getBoundingClientRect();
    const style = getComputedStyle(e);
    return rect.width > 0 && rect.height > 0 &&
           style.display !== "none" && style.visibility !== "hidden";
  };
  const editable = e => shown(e) && !e.disabled && !e.readOnly &&
    e.getAttribute("aria-readonly") !== "true";
  const accessibleName = e => {
    const ids = (e.getAttribute("aria-labelledby") || "").split(/\s+/).filter(Boolean);
    const fromIds = ids.map(id => document.getElementById(id)?.innerText || "");
    return norm([
      e.getAttribute("aria-label"), e.getAttribute("placeholder"),
      e.getAttribute("title"), e.getAttribute("name"), e.innerText,
      ...fromIds,
      ...(e.labels ? [...e.labels].map(x => x.innerText) : []),
    ].filter(Boolean).join(" "));
  };
  const rowName = e => {
    let node = e;
    for (let depth = 0; depth < 4 && node; depth += 1, node = node.parentElement) {
      const text = norm(node.innerText || "");
      if (text.includes("definir data e hora") && text.length < 80) return text;
    }
    return "";
  };
  const isSubmitName = name => /^(publicar|agendar|programar|concluir mais tarde)$/.test(name);
  const switches = [...document.querySelectorAll('[role="switch"], input[type="checkbox"]')];
  const scheduleSwitches = switches.filter(e => {
    const name = accessibleName(e) || rowName(e);
    return name.includes("definir data e hora") && !isSubmitName(name);
  });
  let uniqueSwitches = [...new Set(scheduleSwitches)];
  const namedSwitches = uniqueSwitches.filter(e => e.getAttribute("role") === "switch");
  if (namedSwitches.length === 1) uniqueSwitches = namedSwitches;
  if (uniqueSwitches.length > 1) return response("ambiguous");
  const explicitlyOff = e => e.getAttribute("aria-checked") === "false" ||
    (e.tagName === "INPUT" && (e.type || "").toLowerCase() === "checkbox" &&
     e.checked === false && e.getAttribute("aria-checked") !== "true");
  if (uniqueSwitches.length === 1 && explicitlyOff(uniqueSwitches[0])) {
    const scheduleSwitch = uniqueSwitches[0];
    if (isSubmitName(accessibleName(scheduleSwitch))) return response("rejected");
    scheduleSwitch.click();
    for (let attempt = 0; attempt < 15 && explicitlyOff(scheduleSwitch); attempt += 1) {
      await sleep(100);
    }
  }

  const label = e => accessibleName(e);
  const range = e => {
    const low = e.getAttribute("aria-valuemin") ?? e.getAttribute("min");
    const high = e.getAttribute("aria-valuemax") ?? e.getAttribute("max");
    return (low != null && high != null) ? (low + "-" + high) : "";
  };
  const inputs = () => [...document.querySelectorAll("input")].filter(editable);
  const collect = () => {
    const fields = inputs();
    return {
      date: fields.filter(e =>
        ["text", "date"].includes((e.type || "text").toLowerCase()) &&
        (/\b(data|date)\b/.test(label(e))) &&
        !/\b(nascimento|birth)\b/.test(label(e)) &&
        e.getAttribute("role") !== "spinbutton"),
      hour: fields.filter(e => e.getAttribute("role") === "spinbutton" && range(e) === "0-23"),
      minute: fields.filter(e => e.getAttribute("role") === "spinbutton" && range(e) === "0-59"),
      clock: fields.filter(e => {
        const kind = (e.type || "text").toLowerCase();
        if (!["text", "time"].includes(kind) || e.getAttribute("role") === "spinbutton") return false;
        const name = label(e);
        if (/\b(data|date|nascimento|birth)\b/.test(name)) return false;
        return kind === "time" || /\b(hora|horario|time)\b/.test(name) ||
          /^\d{1,2}:\d{2}$/.test(norm(e.value));
      }),
    };
  };
  let candidates = collect();
  for (let attempt = 0; attempt < 15 &&
      (candidates.date.length !== 1 ||
       !((candidates.hour.length === 1 && candidates.minute.length === 1) ||
         candidates.clock.length === 1)); attempt += 1) {
    await sleep(100);
    candidates = collect();
  }
  const dateList = candidates.date;
  const splitTime = candidates.hour.length === 1 && candidates.minute.length === 1 &&
    candidates.hour[0] !== candidates.minute[0];
  const clockList = candidates.clock.filter(e => !dateList.includes(e));
  const useClock = clockList.length === 1;
  if (dateList.length !== 1 || !(useClock || splitTime)) {
    return response("ambiguous");
  }
  const date = dateList[0];
  const hour = useClock ? null : candidates.hour[0];
  const minute = useClock ? null : candidates.minute[0];
  const clock = useClock ? clockList[0] : null;
  if (new Set([date, hour, minute, clock].filter(Boolean)).size !==
      [date, hour, minute, clock].filter(Boolean).length) {
    return response("ambiguous");
  }

  const before = norm(date.value);
  const dateAsIso = date.type === "date";
  let newDate = target.pt;
  if (dateAsIso || /^\d{4}-\d{2}-\d{2}$/.test(before)) newDate = target.iso;
  else if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(before)) newDate = target.br;
  const hourText = String(target.hour).padStart(2, "0");
  const minuteText = String(target.minute).padStart(2, "0");
  const next = [[date, newDate]];
  if (!useClock) {
    if (!["text", "number"].includes((hour.type || "text").toLowerCase()) ||
        !["text", "number"].includes((minute.type || "text").toLowerCase())) {
      return response("unsupported");
    }
    next.push([hour, hourText], [minute, minuteText]);
  } else {
    if (!["text", "time"].includes((clock.type || "text").toLowerCase())) {
      return response("unsupported");
    }
    next.push([clock, hourText + ":" + minuteText]);
  }
  const setNative = (e, value) => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    if (!setter) return false;
    e.focus();
    setter.call(e, value);
    if (e.getAttribute("role") === "spinbutton") {
      e.setAttribute("aria-valuenow", String(Number(value)));
      e.setAttribute("aria-valuetext", value);
    }
    e.dispatchEvent(new InputEvent("input", {
      bubbles: true, data: value, inputType: "insertReplacementText",
    }));
    e.dispatchEvent(new Event("change", {bubbles: true}));
    e.dispatchEvent(new Event("blur", {bubbles: true}));
    return true;
  };
  const same = (el, value) => {
    if (!document.contains(el)) return false;
    const got = norm(el.value);
    const want = norm(value);
    if (got === want) return true;
    if (/^\d{1,2}$/.test(got) && /^\d{1,2}$/.test(want)) return Number(got) === Number(want);
    const clockGot = got.match(/^(\d{1,2}):(\d{2})$/);
    const clockWant = want.match(/^(\d{1,2}):(\d{2})$/);
    return !!clockGot && !!clockWant &&
      Number(clockGot[1]) === Number(clockWant[1]) &&
      Number(clockGot[2]) === Number(clockWant[2]);
  };
  try {
    for (const [el, value] of next) {
      if (!setNative(el, value)) return response("unsupported");
    }
    await sleep(600);
    if (!next.every(([el, value]) => same(el, value))) return response("rejected");
    return response("verified");
  } catch (_) {
    return response("rejected");
  }
}"""
