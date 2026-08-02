#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
site_tracker.py
===============
United Brothers Co. / الشركة المتحدة إخوان
PROJECT ELEVATE (Bulletproof Enterprise Edition)

Daily Site Voice/Text Log & PPC Engine
محرك السجل اليومي للموقع ونسبة إنجاز الخطة

Capabilities:
  * Ingests daily WhatsApp site notes / voice transcripts (free text).
  * Extracts structured metrics via the Anthropic API
    (claude-3-7-sonnet-20250219) with a deterministic regex fallback:
        - PPC % (Percent Plan Complete)
        - NCRs (Non-Conformance Reports)
        - Equipment uptime / OEE
        - LTI (Lost Time Injuries) — zero-tolerance safety gate
        - Per-staff time allocation
  * Aggregates a period, applies PROJECT ELEVATE gates, and renders a
    branded bilingual Executive Daily Digest for the CEO.

Author: AI Operations Architect — United Brothers Co.
Python: 3.10+
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | ELEVATE-SITE | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("elevate.site")

DEFAULT_RATES_PATH = Path(__file__).with_name("target_rates.json")
ANTHROPIC_MODEL = "claude-3-7-sonnet-20250219"

BRAND = {
    "entity_en": "United Brothers Co.",
    "entity_ar": "الشركة المتحدة إخوان (للمقاولات والتوريدات العمومية والخدمات الصناعية)",
    "navy": "#1B365D",
    "gold": "#D4AF37",
}


# --------------------------------------------------------------------------- #
#  Data models  |  النماذج
# --------------------------------------------------------------------------- #
@dataclass
class StaffAllocation:
    """Time allocation for a staff member on a given day. تخصيص الوقت."""

    name: str
    hours: float
    project: str = ""


@dataclass
class SiteLog:
    """Parsed structured metrics from one daily site note. سجل الموقع."""

    site: str
    date: str
    ppc: Optional[float] = None            # 0.0 - 1.0
    ncr_count: int = 0
    equipment_oee: Optional[float] = None  # 0.0 - 1.0
    lti_count: int = 0
    staff_allocations: list[StaffAllocation] = field(default_factory=list)
    raw_note: str = ""
    highlights: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Tracker  |  المتتبع
# --------------------------------------------------------------------------- #
class SiteTracker:
    def __init__(
        self,
        rates_path: str | Path = DEFAULT_RATES_PATH,
        api_key: Optional[str] = None,
    ) -> None:
        self.rates_path = Path(rates_path)
        self.config = self._load_config(self.rates_path)
        self.gov = self.config["governance"]
        self.safety = self.config["safety"]
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"[CONFIG] target_rates.json not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------------------------ #
    #  Parsing  |  التحليل
    # ------------------------------------------------------------------ #
    def parse_note(self, note: str, site: str = "N/A", date: Optional[str] = None) -> SiteLog:
        date = date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self.api_key:
            try:
                return self._parse_with_anthropic(note, site, date)
            except Exception as exc:
                logger.warning("Anthropic parse failed (%s). Falling back to regex.", exc)
        else:
            logger.info("No ANTHROPIC_API_KEY set — using deterministic regex parser.")
        return self._parse_with_regex(note, site, date)

    def _parse_with_anthropic(self, note: str, site: str, date: str) -> SiteLog:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK not installed (pip install anthropic)") from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        system = (
            "You are a construction site-reporting analyst for United Brothers Co. "
            "Extract structured daily metrics from a WhatsApp site note or voice "
            "transcript (Arabic and/or English). Return strict JSON only."
        )
        prompt = (
            "Extract this exact JSON schema (use null when unknown):\n"
            '{"ppc": number|null (fraction 0-1), "ncr_count": int, '
            '"equipment_oee": number|null (fraction 0-1), "lti_count": int, '
            '"staff_allocations": [{"name": str, "hours": number}], '
            '"highlights": [str]}\n\n'
            f"SITE NOTE:\n{note}"
        )
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            b.text for b in msg.content if getattr(b, "type", "") == "text"
        )
        data = self._extract_json_object(text)
        return self._coerce_log(data, note, site, date)

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any]:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON object found in model response.")
        return json.loads(match.group(0))

    @staticmethod
    def _coerce_log(d: dict[str, Any], note: str, site: str, date: str) -> SiteLog:
        allocs = [
            StaffAllocation(name=str(a.get("name", "")).strip(),
                            hours=float(a.get("hours", 0) or 0))
            for a in d.get("staff_allocations", []) or []
        ]
        return SiteLog(
            site=site,
            date=date,
            ppc=(None if d.get("ppc") in (None, "") else float(d["ppc"])),
            ncr_count=int(d.get("ncr_count", 0) or 0),
            equipment_oee=(None if d.get("equipment_oee") in (None, "")
                           else float(d["equipment_oee"])),
            lti_count=int(d.get("lti_count", 0) or 0),
            staff_allocations=allocs,
            raw_note=note,
            highlights=[str(h) for h in d.get("highlights", []) or []],
        )

    def _parse_with_regex(self, note: str, site: str, date: str) -> SiteLog:
        """Deterministic fallback that scans for labelled metrics.

        Recognised patterns (case-insensitive, EN/AR digits normalised):
            PPC: 87%              /  نسبة الإنجاز: ٨٧٪
            NCR: 2  or  NCRs 2    /  عدم مطابقة: 2
            OEE: 96%  or Uptime 96%
            LTI: 0   or Injury 0  /  إصابات: 0
            Staff: Ahmed 8h, Mona 6h
        """
        text = self._normalize_digits(note)
        log = SiteLog(site=site, date=date, raw_note=note)

        m = re.search(r"(?:ppc|percent plan complete|نسبة\s*الإنجاز)\D*(\d{1,3})\s*%?",
                      text, re.IGNORECASE)
        if m:
            log.ppc = min(1.0, float(m.group(1)) / 100.0)

        m = re.search(r"(?:ncr|non[- ]?conformance|عدم\s*مطابقة)\D*(\d{1,3})",
                      text, re.IGNORECASE)
        if m:
            log.ncr_count = int(m.group(1))

        m = re.search(r"(?:oee|uptime|كفاءة|تشغيل)\D*(\d{1,3})\s*%?", text, re.IGNORECASE)
        if m:
            log.equipment_oee = min(1.0, float(m.group(1)) / 100.0)

        m = re.search(r"(?:lti|lost time|injur\w*|إصاب\w*)\D*(\d{1,3})", text, re.IGNORECASE)
        if m:
            log.lti_count = int(m.group(1))

        # Staff allocations: "Name 8h" / "Name: 8 hrs" / "الاسم ٨ ساعات".
        # A name is a SINGLE token (letters only, no spaces/punctuation) placed
        # immediately before an hour figure. This deliberately avoids sweeping up
        # sentence fragments from free-form prose (the LLM path handles multi-word
        # names; the regex fallback stays conservative to keep the CEO digest clean).
        stopwords = {
            "ppc", "ncr", "oee", "lti", "uptime", "level", "slab", "no", "and",
            "the", "of", "on", "at", "hrs", "hr", "hours", "reported", "injury",
            "lost", "time", "minor", "major", "delivery", "plan",
        }
        for name, hours in re.findall(
            r"([A-Za-z؀-ۿ]{2,20})\s*[:=]?\s*(\d{1,2}(?:\.\d)?)\s*(?:h|hr|hrs|hours|ساع\w*)\b",
            text, re.IGNORECASE,
        ):
            nm = name.strip(" .,،:-'")
            if not nm or nm.lower() in stopwords:
                continue
            log.staff_allocations.append(StaffAllocation(name=nm, hours=float(hours)))

        return log

    @staticmethod
    def _normalize_digits(text: str) -> str:
        """Convert Arabic-Indic digits to ASCII. تحويل الأرقام العربية."""
        arabic = "٠١٢٣٤٥٦٧٨٩"
        table = {ord(a): str(i) for i, a in enumerate(arabic)}
        return text.translate(table)

    # ------------------------------------------------------------------ #
    #  Aggregation  |  التجميع
    # ------------------------------------------------------------------ #
    def aggregate(self, logs: list[SiteLog]) -> dict[str, Any]:
        ppc_vals = [l.ppc for l in logs if l.ppc is not None]
        oee_vals = [l.equipment_oee for l in logs if l.equipment_oee is not None]
        total_ncr = sum(l.ncr_count for l in logs)
        total_lti = sum(l.lti_count for l in logs)

        staff_hours: dict[str, float] = {}
        for l in logs:
            for a in l.staff_allocations:
                staff_hours[a.name] = staff_hours.get(a.name, 0.0) + a.hours

        avg_ppc = sum(ppc_vals) / len(ppc_vals) if ppc_vals else None
        avg_oee = sum(oee_vals) / len(oee_vals) if oee_vals else None

        ppc_gate = float(self.gov["ppc_eligibility_threshold"])
        oee_gate = float(self.gov["oee_uptime_threshold"])
        max_lti = int(self.safety.get("max_lti_allowed", 0))

        return {
            "logs": logs,
            "avg_ppc": avg_ppc,
            "avg_oee": avg_oee,
            "total_ncr": total_ncr,
            "total_lti": total_lti,
            "staff_hours": staff_hours,
            "ppc_pass": (avg_ppc is not None and avg_ppc >= ppc_gate),
            "oee_pass": (avg_oee is not None and avg_oee >= oee_gate),
            "safety_pass": total_lti <= max_lti,
            "ppc_gate": ppc_gate,
            "oee_gate": oee_gate,
        }

    # ------------------------------------------------------------------ #
    #  Executive digest  |  الملخص التنفيذي
    # ------------------------------------------------------------------ #
    def build_digest(self, agg: dict[str, Any], period_label: str = "") -> str:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        def pct(x: Optional[float]) -> str:
            return "—" if x is None else f"{x * 100:,.1f}%"

        def badge(passed: bool, warn: bool = False) -> str:
            if warn:
                return "🟧 WATCH"
            return "🟩 OK" if passed else "🟥 BREACH"

        safety_pass = agg["safety_pass"]
        lines: list[str] = []
        lines.append(f"# {BRAND['entity_en']} — CEO Daily Site Digest")
        lines.append(f"### {BRAND['entity_ar']}")
        lines.append(f"**الملخص التنفيذي اليومي للموقع**")
        lines.append("")
        lines.append(f"- **Period / الفترة:** {period_label or 'Daily'}")
        lines.append(f"- **Generated / الإصدار:** {ts}")
        lines.append(f"- **Sites reported / المواقع:** {len(agg['logs'])}")
        lines.append("")
        if not safety_pass:
            lines.append("> 🟥 **SAFETY ALERT / تحذير السلامة:** Lost Time Injuries recorded. "
                         "Site team is DISQUALIFIED from the performance bonus this period.")
            lines.append("")
        lines.append("---")
        lines.append("## KPI Snapshot | لوحة المؤشرات")
        lines.append("")
        lines.append("| KPI / المؤشر | Value | Gate | Status |")
        lines.append("|---|---:|---:|:--:|")
        lines.append(f"| Avg PPC / متوسط الإنجاز | {pct(agg['avg_ppc'])} | "
                     f"≥ {pct(agg['ppc_gate'])} | {badge(agg['ppc_pass'])} |")
        lines.append(f"| Avg OEE / كفاءة المعدات | {pct(agg['avg_oee'])} | "
                     f"> {pct(agg['oee_gate'])} | {badge(agg['oee_pass'])} |")
        lines.append(f"| Total NCRs / عدم المطابقة | {agg['total_ncr']} | 0 | "
                     f"{badge(agg['total_ncr'] == 0, warn=agg['total_ncr'] > 0)} |")
        lines.append(f"| Total LTIs / إصابات الوقت الضائع | {agg['total_lti']} | 0 | "
                     f"{badge(safety_pass)} |")
        lines.append("")
        lines.append("---")
        lines.append("## Staff Time Allocation | توزيع ساعات العمل")
        lines.append("")
        if agg["staff_hours"]:
            lines.append("| Staff / الموظف | Hours / الساعات |")
            lines.append("|---|---:|")
            for name, hrs in sorted(agg["staff_hours"].items(), key=lambda x: -x[1]):
                lines.append(f"| {name} | {hrs:,.1f} |")
        else:
            lines.append("_No staff allocations captured._")
        lines.append("")
        lines.append("---")
        lines.append("## Site Highlights | أبرز الأحداث")
        lines.append("")
        any_hl = False
        for l in agg["logs"]:
            if l.highlights:
                any_hl = True
                lines.append(f"**{l.site} ({l.date}):**")
                for h in l.highlights:
                    lines.append(f"- {h}")
        if not any_hl:
            lines.append("_No highlights captured._")
        lines.append("")
        lines.append("---")
        lines.append(f"_United Brothers Co. — PROJECT ELEVATE • Navy {BRAND['navy']} / Gold {BRAND['gold']}_")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    def run(self, notes: list[dict[str, str]], period_label: str = "") -> dict[str, Any]:
        """
        notes: list of {"site", "date", "note"} dicts.
        """
        logs = [
            self.parse_note(n.get("note", ""), site=n.get("site", "N/A"),
                            date=n.get("date"))
            for n in notes
        ]
        agg = self.aggregate(logs)
        digest_md = self.build_digest(agg, period_label=period_label)
        return {"logs": logs, "aggregate": agg, "digest_md": digest_md}


# --------------------------------------------------------------------------- #
#  CLI / demo  |  عرض توضيحي
# --------------------------------------------------------------------------- #
_SAMPLE_NOTES = [
    {
        "site": "New Capital Tower B",
        "date": "2026-08-02",
        "note": (
            "Good morning team. PPC today 88%. NCR: 1 minor on rebar spacing. "
            "Crane uptime 96%. LTI 0. Ahmed 9h, Mona 8h, Khaled 10h. "
            "Poured slab level 3, ahead of plan."
        ),
    },
    {
        "site": "Suez Pipe Rack",
        "date": "2026-08-02",
        "note": (
            "نسبة الإنجاز 82%. عدم مطابقة: 0. كفاءة المعدات 94%. إصابات 0. "
            "أحمد ٨ ساعات. تم استلام دفعة الحديد."
        ),
    },
]


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="United Brothers Co. Daily Site Tracker")
    parser.add_argument("--notes", type=str,
                        help="Path to a JSON file: list of {site,date,note}.")
    parser.add_argument("--rates", type=str, default=str(DEFAULT_RATES_PATH))
    parser.add_argument("--period", type=str, default="2026-08-02 Daily")
    parser.add_argument("--out", type=str, default="site_daily_digest.md")
    args = parser.parse_args()

    if args.notes:
        notes = json.loads(Path(args.notes).read_text(encoding="utf-8"))
    else:
        notes = _SAMPLE_NOTES

    tracker = SiteTracker(rates_path=args.rates)
    result = tracker.run(notes, period_label=args.period)
    Path(args.out).write_text(result["digest_md"], encoding="utf-8")
    logger.info("Digest written to %s", args.out)
    print(result["digest_md"])


if __name__ == "__main__":
    _main()
