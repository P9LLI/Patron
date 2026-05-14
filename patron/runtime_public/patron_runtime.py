from __future__ import annotations

import re
from typing import Any

__all__ = ["run"]

_ALLOWED_KEYS = {"q", "tt", "tr", "pd", "cx", "of", "m"}
_TASKS = {"jurisprudencia", "peticao", "parecer", "relatorio"}
_MODES = {"p1", "p2", "p3", "p4", "r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "s1", "s2", "s3", "s4"}


class _InputError(Exception):
    pass


def run(payload: dict) -> dict:
    try:
        data = _normalize(payload)
        if _needs_facts(data):
            return {"ok": 0, "rp": {"nf": 1}}
        return {"ok": 1, "rp": _build(data)}
    except _InputError:
        return {"ok": 0}
    except Exception:
        return {"ok": 0}


def _normalize(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise _InputError()
    if set(payload) - _ALLOWED_KEYS:
        raise _InputError()

    data = {
        "q": _clean(payload.get("q")),
        "tt": _clean(payload.get("tt")).lower(),
        "tr": _tribunals(payload.get("tr")),
        "pd": _clean(payload.get("pd")),
        "cx": _clean(payload.get("cx")),
        "of": _clean(payload.get("of")),
        "m": _clean(payload.get("m")).lower(),
    }
    if len(data["q"]) < 12 or data["tt"] not in _TASKS or not data["tr"] or data["m"] not in _MODES:
        raise _InputError()
    return data


def _build(data: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(part for part in [data["q"], data["cx"], data["of"]] if part).lower()
    return {
        "fp": _focus(data["tt"], text),
        "rs": {
            "tr": data["tr"][:3],
            "pd": _period(data["pd"]),
            "os": 1,
            "rr": 1 if _recent(text, data["pd"]) else 0,
        },
        "dm": _mode(data["tt"], text),
        "st": _structure(data["tt"]),
        "nf": 0,
    }


def _clean(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()[:800]


def _tribunals(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        raw = re.split(r"[,;/|]", value)
    else:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        t = _clean(item).upper()[:16]
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _needs_facts(data: dict[str, Any]) -> bool:
    short_q = len(data["q"]) < 40
    sparse = not data["cx"] or not data["pd"]
    return short_q and sparse


def _period(value: str) -> str:
    if not value:
        return "ni"
    value = value.lower()
    if any(token in value for token in ["recente", "atu", "ano", "mes"]):
        return "rc"
    return "ri"


def _recent(text: str, period: str) -> bool:
    base = f"{text} {period}".lower()
    return any(token in base for token in ["recente", "atu", "ultim", "ano", "mes"])


def _mode(task: str, text: str) -> str:
    combined = f"{task} {text}"
    if any(term in combined for term in ["quadro", "tabela", "topico", "resumo", "objetiv"]):
        return "obj"
    if any(term in combined for term in ["estrateg", "refor", "combate", "contestar"]):
        return "est"
    if task == "parecer":
        return "anl"
    return "obj"


def _focus(task: str, text: str) -> list[str]:
    base = {
        "jurisprudencia": ["prec", "font", "tese"],
        "peticao": ["tese", "fund", "apoio"],
        "parecer": ["quad", "risc", "conc"],
        "relatorio": ["pano", "conv", "font"],
    }.get(task, ["tese", "font"])
    extra: list[str] = []
    if any(term in text for term in ["recurso", "apela", "agravo", "embargo"]):
        extra.append("recu")
    if any(term in text for term in ["prescri", "decad"]):
        extra.append("temp")
    if any(term in text for term in ["nulid", "vicio", "ilegal"]):
        extra.append("vali")
    seen: set[str] = set()
    out: list[str] = []
    for item in [*base, *extra]:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out[:5]


def _structure(task: str) -> list[str]:
    return {
        "jurisprudencia": ["ctx", "tes", "prec", "sint", "font"],
        "peticao": ["fato", "tes", "fund", "prec", "ped"],
        "parecer": ["ques", "quad", "anal", "ent", "conc"],
        "relatorio": ["esc", "pano", "conv", "div", "conc"],
    }.get(task, ["ctx", "tes", "conc"])
