#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
boq_auditor.py
==============
United Brothers Co. / الشركة المتحدة إخوان
PROJECT ELEVATE (Bulletproof Enterprise Edition)

Automated EGP BOQ & Supplier Quote Auditor
مدقق جداول الكميات وعروض الموردين الآلي

Capabilities:
  * Parses raw supplier quotes (free text / CSV-style) into structured line items
    using the Anthropic API (claude-3-7-sonnet-20250219) when available, with a
    deterministic regex fallback for offline / no-key operation.
  * Benchmarks each line against target_rates.json (EGP target rates).
  * Computes Purchase Price Variance (PPV) and total overspend.
  * Flags unapproved scope items (> 10,000 EGP without a signed VO/SI).
  * Evaluates Value Engineering (VE) potential.
  * Generates a branded, bilingual Markdown audit report.

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
    format="%(asctime)s | ELEVATE-BOQ | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("elevate.boq")

DEFAULT_RATES_PATH = Path(__file__).with_name("target_rates.json")
ANTHROPIC_MODEL = "claude-3-7-sonnet-20250219"

# --------------------------------------------------------------------------- #
#  Branding  |  الهوية
# --------------------------------------------------------------------------- #
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
class QuoteLine:
    """A single supplier quote line item. بند عرض السعر."""

    item_code: str
    description: str
    unit: str
    quantity: float
    unit_rate_egp: float
    approved_vo: bool = False  # signed VO / Site Instruction on file

    @property
    def line_total_egp(self) -> float:
        return self.quantity * self.unit_rate_egp


@dataclass
class AuditLine:
    """Audited line with variance analysis. بند مدقق."""

    item_code: str
    description: str
    unit: str
    quantity: float
    quoted_rate_egp: float
    target_rate_egp: Optional[float]
    ppv_per_unit_egp: Optional[float]
    ppv_total_egp: Optional[float]
    variance_pct: Optional[float]
    unapproved_scope_flag: bool
    ve_potential: bool
    flags: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
#  Auditor  |  المدقق
# --------------------------------------------------------------------------- #
class BOQAuditor:
    def __init__(
        self,
        rates_path: str | Path = DEFAULT_RATES_PATH,
        api_key: Optional[str] = None,
    ) -> None:
        self.rates_path = Path(rates_path)
        self.config = self._load_config(self.rates_path)
        self.target_index = {
            r["item_code"]: r for r in self.config.get("target_rates", [])
        }
        self.gov = self.config["governance"]
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")

    # ------------------------------------------------------------------ #
    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"[CONFIG] target_rates.json not found: {path}")
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)

    # ------------------------------------------------------------------ #
    #  Quote parsing (Anthropic + regex fallback)
    #  تحليل العروض
    # ------------------------------------------------------------------ #
    def parse_quote(self, raw_text: str) -> list[QuoteLine]:
        """Parse a raw supplier quote into structured lines."""
        if self.api_key:
            try:
                return self._parse_with_anthropic(raw_text)
            except Exception as exc:  # graceful degrade
                logger.warning("Anthropic parse failed (%s). Falling back to regex.", exc)
        else:
            logger.info("No ANTHROPIC_API_KEY set — using deterministic regex parser.")
        return self._parse_with_regex(raw_text)

    def _parse_with_anthropic(self, raw_text: str) -> list[QuoteLine]:
        try:
            import anthropic
        except ImportError as exc:
            raise RuntimeError("anthropic SDK not installed (pip install anthropic)") from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        known_codes = ", ".join(self.target_index.keys())
        system = (
            "You are a meticulous quantity-surveying assistant for United Brothers Co. "
            "Extract supplier quote line items into strict JSON. Currency is EGP."
        )
        prompt = (
            f"Known internal item codes: {known_codes}\n"
            "Map each quote line to the closest known item_code when possible, "
            "otherwise invent a short UPPER-CASE code.\n"
            "Return ONLY a JSON array; each element: "
            '{"item_code": str, "description": str, "unit": str, '
            '"quantity": number, "unit_rate_egp": number, "approved_vo": bool}.\n\n'
            f"QUOTE:\n{raw_text}"
        )
        msg = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(
            block.text for block in msg.content if getattr(block, "type", "") == "text"
        )
        data = self._extract_json_array(text)
        return [self._coerce_line(d) for d in data]

    @staticmethod
    def _extract_json_array(text: str) -> list[dict[str, Any]]:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError("No JSON array found in model response.")
        return json.loads(match.group(0))

    @staticmethod
    def _coerce_line(d: dict[str, Any]) -> QuoteLine:
        return QuoteLine(
            item_code=str(d.get("item_code", "UNKNOWN")).strip(),
            description=str(d.get("description", "")).strip(),
            unit=str(d.get("unit", "")).strip(),
            quantity=float(d.get("quantity", 0) or 0),
            unit_rate_egp=float(d.get("unit_rate_egp", 0) or 0),
            approved_vo=bool(d.get("approved_vo", False)),
        )

    def _parse_with_regex(self, raw_text: str) -> list[QuoteLine]:
        """
        Deterministic fallback parser.
        Expected pipe/comma format per line:
            item_code | description | unit | quantity | unit_rate_egp [| approved_vo]
        Lines that don't match are skipped with a warning.
        """
        lines: list[QuoteLine] = []
        for i, raw in enumerate(raw_text.splitlines(), start=1):
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            parts = [p.strip() for p in re.split(r"[|,;\t]", raw)]
            if len(parts) < 5:
                logger.warning("Skipping unparsable line %d: %r", i, raw)
                continue
            try:
                line = QuoteLine(
                    item_code=parts[0],
                    description=parts[1],
                    unit=parts[2],
                    quantity=float(re.sub(r"[^\d.\-]", "", parts[3]) or 0),
                    unit_rate_egp=float(re.sub(r"[^\d.\-]", "", parts[4]) or 0),
                    approved_vo=(
                        len(parts) > 5 and parts[5].lower() in ("1", "true", "yes", "y")
                    ),
                )
                lines.append(line)
            except ValueError as exc:
                logger.warning("Skipping malformed line %d (%s): %r", i, exc, raw)
        return lines

    # ------------------------------------------------------------------ #
    #  Audit logic  |  منطق التدقيق
    # ------------------------------------------------------------------ #
    def audit(self, quote_lines: list[QuoteLine]) -> list[AuditLine]:
        threshold = float(self.gov["unapproved_scope_threshold_egp"])
        audited: list[AuditLine] = []

        for q in quote_lines:
            target = self.target_index.get(q.item_code)
            target_rate = float(target["target_rate_egp"]) if target else None
            ve_potential = bool(target.get("ve_potential", False)) if target else False

            ppv_unit = ppv_total = variance_pct = None
            flags: list[str] = []

            if target_rate is not None:
                ppv_unit = q.unit_rate_egp - target_rate      # +ve = overspend
                ppv_total = ppv_unit * q.quantity
                variance_pct = (ppv_unit / target_rate) if target_rate else None
                if ppv_unit > 0:
                    flags.append("OVERSPEND")
                elif ppv_unit < 0:
                    flags.append("UNDER_TARGET")
            else:
                flags.append("NO_TARGET_RATE")

            # Unapproved scope guardrail (> threshold EGP without signed VO/SI).
            unapproved = (q.line_total_egp > threshold) and not q.approved_vo
            if unapproved:
                flags.append("UNAPPROVED_SCOPE")

            # VE evaluation: flag when VE potential exists and there is overspend
            # or the line is a material commodity item.
            if ve_potential:
                flags.append("VE_CANDIDATE")

            audited.append(AuditLine(
                item_code=q.item_code,
                description=q.description,
                unit=q.unit,
                quantity=q.quantity,
                quoted_rate_egp=q.unit_rate_egp,
                target_rate_egp=target_rate,
                ppv_per_unit_egp=ppv_unit,
                ppv_total_egp=ppv_total,
                variance_pct=variance_pct,
                unapproved_scope_flag=unapproved,
                ve_potential=ve_potential,
                flags=flags,
            ))
        return audited

    # ------------------------------------------------------------------ #
    #  Reporting  |  التقرير
    # ------------------------------------------------------------------ #
    def build_report(
        self,
        audited: list[AuditLine],
        supplier: str = "N/A",
        project: str = "N/A",
    ) -> str:
        total_quoted = sum(a.quoted_rate_egp * a.quantity for a in audited)
        total_ppv = sum(a.ppv_total_egp or 0.0 for a in audited)
        overspend_lines = [a for a in audited if (a.ppv_total_egp or 0) > 0]
        unapproved_lines = [a for a in audited if a.unapproved_scope_flag]
        ve_lines = [a for a in audited if a.ve_potential]
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        def egp(x: Optional[float]) -> str:
            return "—" if x is None else f"{x:,.2f}"

        def pct(x: Optional[float]) -> str:
            return "—" if x is None else f"{x * 100:,.1f}%"

        lines: list[str] = []
        lines.append(f"# {BRAND['entity_en']} — BOQ & Quote Audit Report")
        lines.append(f"### {BRAND['entity_ar']}")
        lines.append(f"**تقرير تدقيق جدول الكميات وعرض السعر**")
        lines.append("")
        lines.append(f"- **Supplier / المورد:** {supplier}")
        lines.append(f"- **Project / المشروع:** {project}")
        lines.append(f"- **Generated / تاريخ الإصدار:** {ts}")
        lines.append(f"- **Model / النموذج:** `{ANTHROPIC_MODEL}`"
                     + ("" if self.api_key else " _(regex fallback — no API key)_"))
        lines.append("")
        lines.append("---")
        lines.append("## 1) Executive Summary | الملخص التنفيذي")
        lines.append("")
        lines.append(f"| Metric / المؤشر | Value (EGP) |")
        lines.append(f"|---|---:|")
        lines.append(f"| Total Quoted Value / إجمالي العرض | {egp(total_quoted)} |")
        lines.append(f"| Total Purchase Price Variance (PPV) / إجمالي انحراف السعر | {egp(total_ppv)} |")
        lines.append(f"| Overspend Lines / بنود التجاوز | {len(overspend_lines)} |")
        lines.append(f"| Unapproved Scope Flags / بنود بدون اعتماد | {len(unapproved_lines)} |")
        lines.append(f"| VE Candidates / بنود الهندسة القيمية | {len(ve_lines)} |")
        lines.append("")
        verdict = "🟥 OVERSPEND" if total_ppv > 0 else "🟩 WITHIN / UNDER TARGET"
        lines.append(f"**Overall Verdict / الحكم العام:** {verdict}")
        lines.append("")
        lines.append("---")
        lines.append("## 2) Line-by-Line PPV | تحليل البنود")
        lines.append("")
        lines.append(
            "| Item Code | Description | Unit | Qty | Quoted | Target | PPV/Unit | PPV Total | Var% | Flags |"
        )
        lines.append("|---|---|---|---:|---:|---:|---:|---:|---:|---|")
        for a in audited:
            lines.append(
                f"| {a.item_code} | {a.description} | {a.unit} | {a.quantity:,.2f} | "
                f"{egp(a.quoted_rate_egp)} | {egp(a.target_rate_egp)} | "
                f"{egp(a.ppv_per_unit_egp)} | {egp(a.ppv_total_egp)} | "
                f"{pct(a.variance_pct)} | {', '.join(a.flags) or '—'} |"
            )
        lines.append("")

        if unapproved_lines:
            lines.append("---")
            lines.append("## 3) ⚠️ Unapproved Scope Guardrail | بنود بدون اعتماد")
            lines.append("")
            lines.append(f"> The following lines exceed "
                         f"{self.gov['unapproved_scope_threshold_egp']:,.0f} EGP without a signed "
                         f"VO/Site Instruction and trigger a 50% individual SLA penalty.")
            lines.append("")
            for a in unapproved_lines:
                lines.append(f"- **{a.item_code}** — {a.description}: "
                             f"{egp(a.quoted_rate_egp * a.quantity)} EGP")
            lines.append("")

        if ve_lines:
            lines.append("---")
            lines.append("## 4) 💡 Value Engineering Opportunities | فرص الهندسة القيمية")
            lines.append("")
            lines.append(f"> VE reward: {self.gov['value_engineering_reward_pct'] * 100:.0f}% of "
                         f"validated savings feeds the 20% performance pool.")
            lines.append("")
            for a in ve_lines:
                note = "overspend — priority" if (a.ppv_total_egp or 0) > 0 else "review for alternatives"
                lines.append(f"- **{a.item_code}** — {a.description} ({note})")
            lines.append("")

        lines.append("---")
        lines.append(f"_United Brothers Co. — PROJECT ELEVATE • Navy {BRAND['navy']} / Gold {BRAND['gold']}_")
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    def run(
        self,
        raw_quote: str,
        supplier: str = "N/A",
        project: str = "N/A",
    ) -> dict[str, Any]:
        quote_lines = self.parse_quote(raw_quote)
        audited = self.audit(quote_lines)
        report_md = self.build_report(audited, supplier=supplier, project=project)
        return {
            "quote_lines": quote_lines,
            "audited": audited,
            "report_md": report_md,
        }


# --------------------------------------------------------------------------- #
#  CLI / demo  |  واجهة الأوامر
# --------------------------------------------------------------------------- #
_SAMPLE_QUOTE = """\
# item_code | description | unit | qty | unit_rate_egp | approved_vo
CIV-CONC-C30 | Ready-mix concrete C30 | m3 | 250 | 2600 | no
CIV-STEEL-REBAR | Reinforcement steel | ton | 40 | 47000 | no
MEP-CABLE-CU-4C | 4-core copper cable | m | 800 | 720 | no
GEN-EARTH-EXC | Bulk excavation | m3 | 1500 | 210 | yes
SPECIAL-CRANE | Mobile crane hire 90d | ls | 1 | 850000 | no
"""


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="United Brothers Co. BOQ & Quote Auditor")
    parser.add_argument("--quote", type=str, help="Path to raw supplier quote text file.")
    parser.add_argument("--rates", type=str, default=str(DEFAULT_RATES_PATH),
                        help="Path to target_rates.json.")
    parser.add_argument("--supplier", type=str, default="Sample Supplier")
    parser.add_argument("--project", type=str, default="Suez Plant Expansion")
    parser.add_argument("--out", type=str, default="boq_audit_report.md")
    args = parser.parse_args()

    raw = Path(args.quote).read_text(encoding="utf-8") if args.quote else _SAMPLE_QUOTE
    auditor = BOQAuditor(rates_path=args.rates)
    result = auditor.run(raw, supplier=args.supplier, project=args.project)

    Path(args.out).write_text(result["report_md"], encoding="utf-8")
    logger.info("Report written to %s", args.out)
    print(result["report_md"])


if __name__ == "__main__":
    _main()
