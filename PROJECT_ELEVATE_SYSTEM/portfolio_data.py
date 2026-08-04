#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio_data.py
=================
United Brothers Co. / الاخوة المتحدين للمقاولات
PROJECT ELEVATE — portfolio & period store + governance helpers

Ported from the Claude Design prototype's data model (`ELEVATE Dashboard.dc.html`).
Holds the multi-project / multi-period history that drives the Portfolio tab,
the period switcher, the blocked-money-by-cause split, sparklines and deltas,
plus the pure helper functions the PORT_GUIDE (§3.1) prescribes.

At this volume (a few hundred rows a year) an in-module list is sufficient; swap
for SQLite when periods are closed for real. `Ain Sokhna · Jul 2026` (p1/jul) is
the live scenario the engine computes; the rest are authored closed periods.

Python: 3.10+
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
#  Brand palette (corrected against the real logo — brick red on cream)
# --------------------------------------------------------------------------- #
NAVY = "#1B365D"
NAVY_DEEP = "#122844"   # header / splash
NAVY2 = "#2F4B7C"
GOLD = "#D4AF37"
GOLD2 = "#B8942F"
BRICK = "#B93429"       # crisis / disqualified / holdback == brand red
BRICK_FILL = "#FBEAE8"
GREEN = "#2E7D32"
GREEN_FILL = "#E8F5E9"
AMBER = "#EF6C00"
AMBER_FILL = "#FFF3E0"
CREAM = "#FFFCFA"       # logo field
PAGE_BG = "#E8ECF3"
CARD = "#FFFFFF"
BORDER = "#E7EBF1"
MUTED = "#5B6B82"
MUTED2 = "#8494AA"

# --------------------------------------------------------------------------- #
#  Verdicts, causes, roles, periods
# --------------------------------------------------------------------------- #
VERDICTS = {
    "FULL":    {"en": "Full payout", "ar": "دفع كامل", "s": "Full", "sa": "كامل", "c": GREEN, "f": GREEN_FILL},
    "PARTIAL": {"en": "Partial payout", "ar": "دفع جزئي", "s": "Partial", "sa": "جزئي", "c": AMBER, "f": AMBER_FILL},
    "HOLD":    {"en": "Holdback", "ar": "حجز كامل", "s": "Held", "sa": "محجوز", "c": BRICK, "f": BRICK_FILL},
    "DQ":      {"en": "Safety disqualification", "ar": "استبعاد للسلامة", "s": "Safety DQ", "sa": "استبعاد", "c": BRICK, "f": BRICK_FILL},
    "OPEN":    {"en": "In progress", "ar": "جارية", "s": "Open", "sa": "مفتوحة", "c": MUTED, "f": "#EDF1F6"},
}

CAUSE = {
    "safety": {"en": "Safety disqualification", "ar": "استبعاد للسلامة",
               "owner": "HSE Manager", "ownerAr": "مدير السلامة", "due": "07 Aug", "dueAr": "٧ أغسطس",
               "c": BRICK, "f": BRICK_FILL},
    "cash":   {"en": "Cash below the 75% floor", "ar": "التحصيل أقل من ٧٥٪",
               "owner": "Commercial", "ownerAr": "التجاري", "due": "31 Aug", "dueAr": "٣١ أغسطس",
               "c": BRICK, "f": BRICK_FILL},
    "gate":   {"en": "Short of the 85% cash gate", "ar": "أقل من بوابة التحصيل ٨٥٪",
               "owner": "Commercial", "ownerAr": "التجاري", "due": "31 Aug", "dueAr": "٣١ أغسطس",
               "c": AMBER, "f": AMBER_FILL},
}

ROLES = [
    {"k": "exec", "en": "Executive", "ar": "تنفيذي"},
    {"k": "mgr", "en": "Project Manager", "ar": "مدير مشروع"},
    {"k": "member", "en": "Team Member", "ar": "عضو فريق"},
]

# Which tabs each role may see (server-side scoping, PORT_GUIDE §5.1).
ROLE_TABS = {
    "exec":   ["pf", "exec", "team", "boq", "site", "dl"],
    "mgr":    ["exec", "team", "boq", "site", "dl"],
    "member": ["site"],
}

PERIODS = [
    {"k": "apr", "en": "Apr 2026", "ar": "أبريل ٢٠٢٦"},
    {"k": "may", "en": "May 2026", "ar": "مايو ٢٠٢٦"},
    {"k": "jun", "en": "Jun 2026", "ar": "يونيو ٢٠٢٦"},
    {"k": "jul", "en": "Jul 2026", "ar": "يوليو ٢٠٢٦"},
    {"k": "aug", "en": "Aug 2026", "ar": "أغسطس ٢٠٢٦"},
]

HANDOVER = {"p1": {"en": "Mar 2027", "ar": "مارس ٢٠٢٧"}, "p2": {"en": "Nov 2026", "ar": "نوفمبر ٢٠٢٦"},
            "p3": {"en": "Jun 2027", "ar": "يونيو ٢٠٢٧"}, "p4": {"en": "Sep 2026", "ar": "سبتمبر ٢٠٢٦"}}

# Escalation owners / SLA — governance config (PORT_GUIDE §5.2). Mirrors the
# block recommended for target_rates.json; kept here so the store is self-contained.
ESCALATION_OWNERS = {
    "safety": {"owner": "HSE Manager", "channels": ["whatsapp", "email"], "sla_days": 5},
    "cash":   {"owner": "Commercial", "channels": ["email"], "sla_days": 30},
    "gate":   {"owner": "Commercial", "channels": ["email"], "sla_days": 30},
}

# Owner → delivery address for real escalation sending (escalation_sender.py).
# Placeholders on purpose — edit here (or mirror in target_rates.json) with the
# real distribution inbox / WhatsApp number. Empty values simply skip that
# channel; credentials for the transport itself come from env / Streamlit
# secrets, never from this file.
ESCALATION_CONTACTS = {
    "HSE Manager": {"email": "hse@unitedbrothers.example",       "whatsapp": ""},
    "Commercial":  {"email": "commercial@unitedbrothers.example", "whatsapp": ""},
}

# Per-(project, period) history. r=released(immediate 70%), c=cash%, p=avg PPC,
# b=blocked EGP, cs=blocking cause, s=net savings. Ain Sokhna/jul is the live one.
PROJECTS = [
    {"id": "p1", "name": "Ain Sokhna — Industrial Warehouse", "nameAr": "العين السخنة — مستودع صناعي",
     "code": "AS-IW-04", "region": "Ain Sokhna", "regionAr": "العين السخنة", "paid": 3, "members": 4,
     "periods": [
         {"k": "apr", "v": "FULL", "r": 612400, "c": 88, "p": 89, "b": 0, "s": 2610000},
         {"k": "may", "v": "FULL", "r": 588900, "c": 87, "p": 90, "b": 0, "s": 2505000},
         {"k": "jun", "v": "PARTIAL", "r": 470220, "c": 81, "p": 86, "b": 34100, "cs": "gate", "s": 2140000},
         {"k": "jul", "v": "PARTIAL", "r": 541130, "c": 82, "p": 84, "b": 28282, "cs": "gate", "s": 2289500},
         {"k": "aug", "v": "OPEN", "r": None, "c": None, "p": None, "b": 0, "s": None}]},
    {"id": "p2", "name": "New Administrative Capital — Tower B", "nameAr": "العاصمة الإدارية — برج ب",
     "code": "NAC-TB-11", "region": "New Administrative Capital", "regionAr": "العاصمة الإدارية", "paid": 6, "members": 6,
     "periods": [
         {"k": "apr", "v": "FULL", "r": 701500, "c": 90, "p": 87, "b": 0, "s": 2860000},
         {"k": "may", "v": "PARTIAL", "r": 512300, "c": 83, "p": 85, "b": 41800, "cs": "gate", "s": 2970000},
         {"k": "jun", "v": "FULL", "r": 744800, "c": 92, "p": 89, "b": 0, "s": 3040000},
         {"k": "jul", "v": "FULL", "r": 769300, "c": 91, "p": 88, "b": 0, "s": 3140000},
         {"k": "aug", "v": "OPEN", "r": None, "c": None, "p": None, "b": 0, "s": None}]},
    {"id": "p3", "name": "Suez — Pipe Rack", "nameAr": "السويس — حاملات المواسير",
     "code": "SUZ-PR-02", "region": "Suez", "regionAr": "السويس", "paid": 0, "members": 5,
     "periods": [
         {"k": "apr", "v": "PARTIAL", "r": 388400, "c": 79, "p": 86, "b": 52300, "cs": "gate", "s": 1580000},
         {"k": "may", "v": "HOLD", "r": 0, "c": 72, "p": 82, "b": 476900, "cs": "cash", "s": 1495000},
         {"k": "jun", "v": "HOLD", "r": 0, "c": 70, "p": 83, "b": 484200, "cs": "cash", "s": 1440000},
         {"k": "jul", "v": "HOLD", "r": 0, "c": 68, "p": 84, "b": 493500, "cs": "cash", "s": 1410000},
         {"k": "aug", "v": "OPEN", "r": None, "c": None, "p": None, "b": 0, "s": None}]},
    {"id": "p4", "name": "Greater Cairo — Logistics Hub", "nameAr": "القاهرة الكبرى — مركز لوجستي",
     "code": "GC-LH-07", "region": "Greater Cairo", "regionAr": "القاهرة الكبرى", "paid": 0, "members": 7,
     "periods": [
         {"k": "apr", "v": "FULL", "r": 498200, "c": 89, "p": 88, "b": 0, "s": 1745000},
         {"k": "may", "v": "FULL", "r": 523700, "c": 90, "p": 87, "b": 0, "s": 1830000},
         {"k": "jun", "v": "FULL", "r": 561900, "c": 91, "p": 88, "b": 0, "s": 1960000},
         {"k": "jul", "v": "DQ", "r": 0, "c": 88, "p": 86, "b": 705250, "cs": "safety", "s": 2015000},
         {"k": "aug", "v": "OPEN", "r": None, "c": None, "p": None, "b": 0, "s": None}]},
]

MAX_RELEASED = 769300  # for bar/sparkline scaling


# --------------------------------------------------------------------------- #
#  Pure helpers (PORT_GUIDE §3.1)
# --------------------------------------------------------------------------- #
def get_project(pid: str) -> dict:
    return next(p for p in PROJECTS if p["id"] == pid)


def get_period_row(pid: str, pk: str) -> dict:
    return next(x for x in get_project(pid)["periods"] if x["k"] == pk)


def period_label(pk: str, lang: str = "en") -> str:
    return next(p[lang] for p in PERIODS if p["k"] == pk)


def fmt(n) -> str:
    return "—" if n is None else f"{int(round(n)):,}"


def blocking_cause(cash_gate_status: str, safety_disqualified: bool):
    """Which gate actually bound — safety first, always."""
    if safety_disqualified:
        return "safety"
    if cash_gate_status == "HOLDBACK":
        return "cash"
    if cash_gate_status == "PARTIAL_UNLOCK":
        return "gate"
    return None


def unlock_forecast(cause: str | None, blocked_egp: float, cash_pct: float):
    """What releases at the next threshold (PORT_GUIDE §3.1)."""
    if cause == "gate":
        return {"recoverable": blocked_egp, "points_needed": round(85 - cash_pct * 100, 1)}
    if cause == "cash":
        pool = blocked_egp
        return {"recoverable": pool * (0.75 / 0.85) * 0.70, "points_needed": round(75 - cash_pct * 100, 1)}
    return {"recoverable": None, "points_needed": None}


def rate_coverage(audited: list) -> float:
    """Σ(quoted value where target exists) / Σ(quoted value) — PORT_GUIDE §3.1."""
    total = sum((a.quoted_rate_egp or 0) * (a.quantity or 0) for a in audited)
    covered = sum((a.quoted_rate_egp or 0) * (a.quantity or 0)
                  for a in audited if a.target_rate_egp is not None)
    return (covered / total) if total else 1.0


def spark_points(project: dict) -> str:
    """SVG polyline points for a project's released-per-period sparkline."""
    closed = [x for x in project["periods"] if x["r"] is not None]
    n = len(closed)
    if n < 2:
        return ""
    return " ".join(
        f"{i * (64 / (n - 1)):.1f},{19 - (x['r'] / MAX_RELEASED) * 17:.1f}"
        for i, x in enumerate(closed))


def delta_vs_prior(project: dict, pk: str, lang: str = "en"):
    """(text, color) delta of released vs the prior closed period."""
    periods = project["periods"]
    row = next(x for x in periods if x["k"] == pk)
    idx = periods.index(row)
    prev = periods[idx - 1] if idx > 0 else None
    if row["r"] is None or not prev or prev["r"] is None:
        return ("—", "#A8B4C6")
    if prev["r"] == 0 and row["r"] == 0:
        return ("still nil" if lang == "en" else "لا شيء", BRICK)
    if prev["r"] == 0:
        return ("restarted" if lang == "en" else "استؤنف", GREEN)
    d = (row["r"] - prev["r"]) / prev["r"] * 100
    txt = ("+" if d > 0 else "−") + f"{abs(d):.1f}%"
    col = GREEN if d > 1 else BRICK if d < -1 else MUTED
    return (txt, col)


def portfolio_totals(pk: str) -> dict:
    """Aggregate released / savings / retained / paying / blocked for a period."""
    released = savings = retained = blocked = 0
    paying = 0
    blocked_rows = []
    for p in PROJECTS:
        row = get_period_row(p["id"], pk)
        if row["r"]:
            released += row["r"]
            paying += 1
        if row["s"]:
            savings += row["s"]
        # retained 30% cushion ~ released/0.7*0.3 for paying periods
        if row["r"]:
            retained += row["r"] / 0.70 * 0.30
        if row.get("b"):
            blocked += row["b"]
            blocked_rows.append({"project": p, "row": row, "cause": row.get("cs")})
    blocked_rows.sort(key=lambda x: -x["row"]["b"])
    return {"released": released, "savings": savings, "retained": retained,
            "paying": paying, "blocked": blocked, "blocked_rows": blocked_rows}
