#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_pipeline.py
===============
United Brothers Co. / الشركة المتحدة إخوان
PROJECT ELEVATE (Bulletproof Enterprise Edition)

End-to-End Orchestrator (A → Z)
منسّق التشغيل الكامل من الألف إلى الياء

Runs the full PROJECT ELEVATE pipeline in one command:
  1) BOQ & quote audit          → outputs/boq_audit_report.md
  2) Daily site digest          → outputs/site_daily_digest.md
  3) Adaptive gainsharing        → outputs/gainsharing_result.md
  4) Live branded master workbook → outputs/UNITED_BROTHERS_ELEVATE_MASTER.xlsx

Each stage degrades gracefully and reports its own status, so a failure in one
module never blocks the others. Set ANTHROPIC_API_KEY to enable AI parsing in
stages 1 & 2 (otherwise the deterministic regex fallback is used).

Author: AI Operations Architect — United Brothers Co.
Python: 3.10+
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | ELEVATE-PIPELINE | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("elevate.pipeline")

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

DEFAULT_RATES = HERE / "target_rates.json"
DEFAULT_QUOTE = HERE / "sample_inputs" / "supplier_quote.txt"
DEFAULT_NOTES = HERE / "sample_inputs" / "site_notes.json"


def _demo_scenario(rates_path: Path):
    """Build the demo ProjectFinancials + team for the gainsharing stage."""
    from gainsharing_calculator import ProjectFinancials, TeamMember

    fin = ProjectFinancials(
        project_name="Ain Sokhna Industrial Warehouse",
        baseline_cost_egp=12_000_000.0, actual_cost_egp=10_400_000.0,
        cash_collected_pct=0.82, quality_factor=0.95,
        escalation_commodity="steel_rebar", bad_debt_egp=150_000.0,
        subcontractor_value_egp=3_000_000.0, lost_time_injuries=0,
    )
    members = [
        TeamMember("Ahmed Fathy", "Site Manager", time_weight=1.0, ld_badge="Level 3",
                   ppc=0.92, equipment_oee=0.97, vo_settlement_days=5,
                   value_engineering_savings_egp=200_000),
        TeamMember("Mona Adel", "QA/QC Engineer", time_weight=0.8, ld_badge="Level 2",
                   ppc=0.88, ld_sla_met=False),
        TeamMember("Khaled Samir", "Foreman", time_weight=1.0, ld_badge="Level 1", ppc=0.70),
        TeamMember("Sara Nabil", "Planner", time_weight=0.5, ld_badge="Level 2",
                   ppc=0.90, resigning_clean_handover=True, kaizen_points=2),
    ]
    return fin, members


def run_pipeline(
    rates_path: Path = DEFAULT_RATES,
    quote_path: Path = DEFAULT_QUOTE,
    notes_path: Path = DEFAULT_NOTES,
    out_dir: Path = HERE / "outputs",
) -> dict[str, str]:
    """Run all four stages. Returns a {stage: status} report."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, str] = {}

    # --- Stage 1: BOQ audit ---
    try:
        from boq_auditor import BOQAuditor
        raw = quote_path.read_text(encoding="utf-8")
        auditor = BOQAuditor(rates_path=rates_path)
        res = auditor.run(raw, supplier="Delta Industrial Supplies",
                          project="New Capital Tower B")
        (out_dir / "boq_audit_report.md").write_text(res["report_md"], encoding="utf-8")
        report["1_boq_audit"] = f"OK — {len(res['audited'])} lines audited"
    except Exception as exc:  # graceful degrade
        logger.exception("BOQ stage failed")
        report["1_boq_audit"] = f"FAILED — {exc}"

    # --- Stage 2: Site digest ---
    try:
        import json
        from site_tracker import SiteTracker
        notes = json.loads(notes_path.read_text(encoding="utf-8"))
        tracker = SiteTracker(rates_path=rates_path)
        res = tracker.run(notes, period_label="Pipeline Run")
        (out_dir / "site_daily_digest.md").write_text(res["digest_md"], encoding="utf-8")
        agg = res["aggregate"]
        safety = "SAFE" if agg["safety_pass"] else "LTI-DISQUALIFIED"
        report["2_site_digest"] = f"OK — {len(res['logs'])} sites, {safety}"
    except Exception as exc:
        logger.exception("Site stage failed")
        report["2_site_digest"] = f"FAILED — {exc}"

    # --- Stage 3: Gainsharing ---
    gs_result = None
    try:
        from gainsharing_calculator import GainsharingCalculator
        fin, members = _demo_scenario(rates_path)
        calc = GainsharingCalculator(rates_path=rates_path)
        gs_result = calc.run(fin, members)
        md = gs_result.summary() + "\n\n## Audit Trail\n" + gs_result.audit_df.to_markdown(index=False)
        (out_dir / "gainsharing_result.md").write_text(md, encoding="utf-8")
        pool = gs_result.pool_df.iloc[0]
        report["3_gainsharing"] = (
            f"OK — S={pool['net_savings_S_egp']:,.0f} EGP, "
            f"gate={pool['cash_gate_status']}"
        )
    except Exception as exc:
        logger.exception("Gainsharing stage failed")
        report["3_gainsharing"] = f"FAILED — {exc}"

    # --- Stage 4: Live master workbook ---
    try:
        from export_excel_template import ElevateWorkbookBuilder
        builder = ElevateWorkbookBuilder(rates_path=rates_path, gainsharing_result=gs_result)
        path = builder.build(out_dir / "UNITED_BROTHERS_ELEVATE_MASTER.xlsx")
        mode = "LIVE" if gs_result is not None else "TEMPLATE"
        report["4_master_workbook"] = f"OK — {mode} — {path.name}"
    except Exception as exc:
        logger.exception("Excel stage failed")
        report["4_master_workbook"] = f"FAILED — {exc}"

    return report


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="United Brothers Co. — PROJECT ELEVATE end-to-end pipeline")
    parser.add_argument("--rates", type=Path, default=DEFAULT_RATES)
    parser.add_argument("--quote", type=Path, default=DEFAULT_QUOTE)
    parser.add_argument("--notes", type=Path, default=DEFAULT_NOTES)
    parser.add_argument("--out", type=Path, default=HERE / "outputs")
    args = parser.parse_args()

    logger.info("Starting PROJECT ELEVATE pipeline (A → Z)...")
    report = run_pipeline(args.rates, args.quote, args.notes, args.out)

    print("\n" + "=" * 60)
    print("  UNITED BROTHERS CO. — PROJECT ELEVATE — PIPELINE REPORT")
    print("=" * 60)
    failed = False
    for stage, status in sorted(report.items()):
        icon = "✅" if status.startswith("OK") else "❌"
        if not status.startswith("OK"):
            failed = True
        print(f"  {icon}  {stage:20} {status}")
    print("=" * 60)
    print(f"  Outputs written to: {args.out}")
    print("=" * 60 + "\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_main())
