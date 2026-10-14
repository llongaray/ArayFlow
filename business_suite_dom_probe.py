"""Sondagem DOM SOMENTE LEITURA do compositor Meta.

O JavaScript nao envia requisicoes, nao altera controles e nao retorna
texto, valores, URLs, IDs do DOM, cookies ou dados da conta.
So permite metadados enumerados e limites numericos padronizados.
"""
from __future__ import annotations

import json
import re

READ_ONLY_SCHEDULE_JS = r"""() => {
  if (location.hostname !== "business.facebook.com") {
    return {probe: "arayflow-dom-v1", status: "wrong-host", total: 0, controls: []};
  }
  const selector = 'input:not([type="hidden"]), select, textarea, [role="combobox"], [role="spinbutton"], [contenteditable="true"]';
  const seen = new Set();
  const controls = [];
  const classify = (source) => {
    const s = (source || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    if (/\b(minutos?|minutes?)\b/.test(s)) return "minute";
    if (/\b(hora|horario|hours?)\b/.test(s)) return "hour";
    if (/\b(mes|month|janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\b/.test(s)) return "month";
    if (/\b(ano|year)\b/.test(s)) return "year";
    if (/\b(dia|day)\b/.test(s)) return "day";
    if (/\b(data|date)\b/.test(s)) return "date";
    if (/\b(texto|legenda|caption|post)\b/.test(s)) return "caption";
    return "unknown";
  };
  const enumRole = (role) => ["combobox", "spinbutton", "textbox", "button"].includes(role) ? role : "none";
  const enumType = (type) => ["text", "date", "time", "number", "search", "month", "datetime-local"].includes(type) ? type : "other";
  const safeRange = (el) => {
    const mn = el.getAttribute("aria-valuemin") ?? el.getAttribute("min");
    const mx = el.getAttribute("aria-valuemax") ?? el.getAttribute("max");
    const min = Number(mn), max = Number(mx);
    if (!mn || !mx || !Number.isFinite(min) || !Number.isFinite(max)) return "unknown";
    if (min === 0 && max === 23) return "hour-24";
    if (min === 1 && max === 12) return "hour-12-or-month";
    if (min === 0 && max === 59) return "minute";
    if (min === 1 && max === 31) return "day";
    return "other";
  };
  for (const el of document.querySelectorAll(selector)) {
    if (seen.has(el)) continue;
    seen.add(el);
    const rect = el.getBoundingClientRect();
    const css = getComputedStyle(el);
    if (!rect.width || !rect.height || css.display === "none" || css.visibility === "hidden") continue;
    const tag = ["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName) ? el.tagName.toLowerCase() : "other";
    const role = enumRole(el.getAttribute("role"));
    const labels = [
      el.getAttribute("aria-label"),
      el.getAttribute("placeholder"),
      el.getAttribute("title"),
      el.getAttribute("name"),
      ...(el.labels ? [...el.labels].map(x => x.textContent) : []),
    ].filter(Boolean).join(" ");
    controls.push({
      tag,
      role,
      input: tag === "input" ? enumType((el.getAttribute("type") || "text").toLowerCase()) : "none",
      label: classify(labels),
      labelPresent: !!labels,
      range: safeRange(el),
      popup: ["listbox", "dialog", "grid"].includes(el.getAttribute("aria-haspopup"))
        ? el.getAttribute("aria-haspopup") : "none",
      readonly: !!el.readOnly || el.getAttribute("aria-readonly") === "true",
      editable: el.getAttribute("contenteditable") === "true",
    });
  }
  return {
    probe: "arayflow-dom-v1",
    status: "ok",
    total: controls.length,
    controls: controls.slice(0, 35),
    truncated: controls.length > 35,
  };
}"""

_ALLOWED = {
    "tag": {"input", "select", "textarea", "other"},
    "role": {"combobox", "spinbutton", "textbox", "button", "none"},
    "input": {"text", "date", "time", "number", "search", "month", "datetime-local", "other", "none"},
    "label": {"minute", "hour", "month", "year", "day", "date", "caption", "unknown"},
    "range": {"hour-24", "hour-12-or-month", "minute", "day", "month", "other", "unknown"},
    "popup": {"listbox", "dialog", "grid", "none"},
}


def format_dom_probe(mcp_text: str) -> list[str]:
    """Exibe apenas campos expressamente permitidos; nao imprime retorno bruto."""
    decoder = json.JSONDecoder()
    result = None
    for match in re.finditer(r"\{", mcp_text):
        try:
            obj, _ = decoder.raw_decode(mcp_text[match.start():])
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(obj, dict) and obj.get("probe") == "arayflow-dom-v1":
            result = obj
            break
    if result is None:
        return ["[DOM] Resposta do MCP nao interpretada; dados brutos descartados."]
    if result.get("status") == "wrong-host":
        return ["[DOM] A aba deixou de ser o Business Suite; inspecao DOM cancelada."]
    if result.get("status") != "ok":
        return ["[DOM] Sondagem DOM nao confirmou estado seguro."]
    items = result.get("controls")
    if not isinstance(items, list):
        return ["[DOM] Formato dos controles inesperado."]
    total = result.get("total")
    total = min(total, 999) if type(total) is int and 0 <= total else len(items)
    output = [f"[DOM] Controles de formulario visiveis: {total}"]
    for n, item in enumerate(items[:35], start=1):
        if not isinstance(item, dict):
            continue
        fields = {
            key: (item.get(key) if item.get(key) in choices else "unknown")
            for key, choices in _ALLOWED.items()
        }
        output.append(
            "[DOM] #{} {} role={} tipo={} rotulo={} presente={} "
            "limites={} popup={} editavel={} somente_leitura={}".format(
                n, fields["tag"], fields["role"], fields["input"],
                fields["label"], "SIM" if item.get("labelPresent") is True else "NAO",
                fields["range"], fields["popup"],
                "SIM" if item.get("editable") is True else "NAO",
                "SIM" if item.get("readonly") is True else "NAO",
            )
        )
    if result.get("truncated") is True:
        output.append("[DOM] Controles extras omitidos pelo limite de 35.")
    return output
