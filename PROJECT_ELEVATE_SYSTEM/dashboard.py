#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py
============
United Brothers Co. / الاخوة المتحدين للمقاولات
PROJECT ELEVATE (Bulletproof Enterprise Edition)

Interactive Web Dashboard (Streamlit)
لوحة تحكم تفاعلية

A visual, no-code front end for the whole PROJECT ELEVATE pipeline. Enter the
project financials and team, optionally upload a supplier quote and site notes,
click "Run", and see the gainsharing result, BOQ audit, and site KPIs — then
download the branded master workbook and reports.

Run locally:   streamlit run dashboard.py
Deploy free:   Streamlit Community Cloud (see docs/DEPLOY.md)

Python: 3.10+
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

# Make the flat PROJECT_ELEVATE_SYSTEM modules importable when this file is the
# Streamlit entry point (Streamlit runs it as __main__).
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from boq_auditor import BOQAuditor  # noqa: E402
from site_tracker import SiteTracker  # noqa: E402
from gainsharing_calculator import (  # noqa: E402
    GainsharingCalculator, ProjectFinancials, TeamMember,
)
from export_excel_template import ElevateWorkbookBuilder  # noqa: E402

RATES_PATH = HERE / "target_rates.json"
SAMPLE_QUOTE = HERE / "sample_inputs" / "supplier_quote.txt"
SAMPLE_NOTES = HERE / "sample_inputs" / "site_notes.json"

ENTITY_EN = "United Brothers Co."
ENTITY_AR = "الاخوة المتحدين للمقاولات"
NAVY = "#1B365D"
GOLD = "#D4AF37"

# --------------------------------------------------------------------------- #
#  Page setup & branding
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="PROJECT ELEVATE — United Brothers Co.",
                   page_icon="🏗️", layout="wide")

st.markdown(f"""
<style>
  .ub-header {{
    background: {NAVY}; color: white; padding: 18px 24px; border-radius: 10px;
    border-left: 8px solid {GOLD}; margin-bottom: 6px;
  }}
  .ub-header h1 {{ margin: 0; font-size: 26px; }}
  .ub-header .ar {{ color: {GOLD}; font-size: 20px; direction: rtl; }}
  .ub-sub {{ color: #ccc; font-size: 14px; }}
  div[data-testid="stMetricValue"] {{ font-size: 22px; }}
</style>
<div class="ub-header">
  <h1>🏗️ {ENTITY_EN} &nbsp;|&nbsp; <span class="ar">{ENTITY_AR}</span></h1>
  <div class="ub-sub">PROJECT ELEVATE — Gainsharing, KPI & Operations Dashboard
  &nbsp;•&nbsp; لوحة المشاركة في المكاسب والمؤشرات</div>
</div>
""", unsafe_allow_html=True)


def _load_config() -> dict:
    with RATES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


CONFIG = _load_config()
COMMODITIES = list(CONFIG["material_escalation_index"].keys())


# --------------------------------------------------------------------------- #
#  Sidebar — inputs
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("① Project financials | المالية")
    project_name = st.text_input("Project name / المشروع", "Ain Sokhna Industrial Warehouse")
    baseline = st.number_input("Baseline cost (EGP) / التكلفة الأساسية",
                               min_value=0.0, value=12_000_000.0, step=100_000.0)
    actual = st.number_input("Actual cost (EGP) / التكلفة الفعلية",
                             min_value=0.0, value=10_400_000.0, step=100_000.0)
    cash_pct = st.slider("Cash collected % / نسبة التحصيل", 0, 100, 82) / 100.0
    quality = st.slider("Quality factor / معامل الجودة", 0.0, 1.0, 0.95, 0.01)
    commodity = st.selectbox("Escalation commodity / سلعة التصاعد",
                             COMMODITIES, index=COMMODITIES.index("steel_rebar")
                             if "steel_rebar" in COMMODITIES else 0)
    bad_debt = st.number_input("Bad debt (EGP) / ديون معدومة",
                               min_value=0.0, value=150_000.0, step=10_000.0)
    subk = st.number_input("Subcontractor value (EGP) / قيمة المقاول",
                           min_value=0.0, value=3_000_000.0, step=100_000.0)
    lti = st.number_input("Lost Time Injuries (LTI) / إصابات", min_value=0, value=0, step=1)

    st.divider()
    st.header("② Data files | الملفات")
    quote_file = st.file_uploader("Supplier quote (.txt) / عرض المورد", type=["txt"])
    notes_file = st.file_uploader("Site notes (.json) / ملاحظات الموقع", type=["json"])
    st.caption("Leave empty to use the built-in sample data.")


# --------------------------------------------------------------------------- #
#  Team editor
# --------------------------------------------------------------------------- #
st.subheader("③ Team & individual KPIs | الفريق والمؤشرات الفردية")
default_team = pd.DataFrame([
    {"name": "Ahmed Fathy", "role": "Site Manager", "ld_badge": "Level 3",
     "time_weight": 1.0, "ppc": 0.92, "section_sla_met": True, "ld_sla_met": True,
     "equipment_oee": 0.97, "vo_settlement_days": 5, "value_engineering_savings_egp": 200_000,
     "kaizen_points": 0, "resigning_clean_handover": False, "unapproved_scope_breach": False},
    {"name": "Mona Adel", "role": "QA/QC Engineer", "ld_badge": "Level 2",
     "time_weight": 0.8, "ppc": 0.88, "section_sla_met": True, "ld_sla_met": False,
     "equipment_oee": 0.0, "vo_settlement_days": 0, "value_engineering_savings_egp": 0,
     "kaizen_points": 0, "resigning_clean_handover": False, "unapproved_scope_breach": False},
    {"name": "Khaled Samir", "role": "Foreman", "ld_badge": "Level 1",
     "time_weight": 1.0, "ppc": 0.70, "section_sla_met": True, "ld_sla_met": True,
     "equipment_oee": 0.0, "vo_settlement_days": 0, "value_engineering_savings_egp": 0,
     "kaizen_points": 0, "resigning_clean_handover": False, "unapproved_scope_breach": False},
    {"name": "Sara Nabil", "role": "Planner", "ld_badge": "Level 2",
     "time_weight": 0.5, "ppc": 0.90, "section_sla_met": True, "ld_sla_met": True,
     "equipment_oee": 0.0, "vo_settlement_days": 0, "value_engineering_savings_egp": 0,
     "kaizen_points": 2, "resigning_clean_handover": True, "unapproved_scope_breach": False},
])
team_df = st.data_editor(
    default_team, num_rows="dynamic", width="stretch",
    column_config={
        "ld_badge": st.column_config.SelectboxColumn(
            "L&D Badge", options=["Level 1", "Level 2", "Level 3"]),
        "ppc": st.column_config.NumberColumn("PPC", min_value=0.0, max_value=1.0, step=0.01),
        "time_weight": st.column_config.NumberColumn("Time wt", min_value=0.0, max_value=1.0, step=0.05),
    },
)

run = st.button("▶  Run PROJECT ELEVATE", type="primary", width="stretch")


# --------------------------------------------------------------------------- #
#  Pipeline runner (in-memory)
# --------------------------------------------------------------------------- #
def _members_from_df(df: pd.DataFrame) -> list[TeamMember]:
    members = []
    for _, r in df.iterrows():
        if not str(r.get("name", "")).strip():
            continue
        vo = r.get("vo_settlement_days", 0)
        members.append(TeamMember(
            name=str(r["name"]), role=str(r.get("role", "")),
            time_weight=float(r.get("time_weight", 1.0) or 0),
            ld_badge=str(r.get("ld_badge", "Level 1")),
            section_sla_met=bool(r.get("section_sla_met", True)),
            ppc=float(r.get("ppc", 0.0) or 0),
            ld_sla_met=bool(r.get("ld_sla_met", True)),
            unapproved_scope_breach=bool(r.get("unapproved_scope_breach", False)),
            resigning_clean_handover=bool(r.get("resigning_clean_handover", False)),
            value_engineering_savings_egp=float(r.get("value_engineering_savings_egp", 0) or 0),
            kaizen_points=float(r.get("kaizen_points", 0) or 0),
            equipment_oee=float(r.get("equipment_oee", 0) or 0),
            vo_settlement_days=int(vo) if str(vo).strip() not in ("", "0", "nan", "None") else None,
        ))
    return members


def run_pipeline_inmemory() -> dict:
    # --- Gainsharing ---
    fin = ProjectFinancials(
        project_name=project_name, baseline_cost_egp=baseline, actual_cost_egp=actual,
        cash_collected_pct=cash_pct, quality_factor=quality,
        escalation_commodity=commodity, bad_debt_egp=bad_debt,
        subcontractor_value_egp=subk, lost_time_injuries=int(lti),
    )
    gs = GainsharingCalculator(rates_path=RATES_PATH).run(fin, _members_from_df(team_df))

    # --- BOQ audit ---
    quote_text = (quote_file.read().decode("utf-8") if quote_file
                  else SAMPLE_QUOTE.read_text(encoding="utf-8"))
    boq = BOQAuditor(rates_path=RATES_PATH).run(
        quote_text, supplier="Dashboard", project=project_name)

    # --- Site digest ---
    notes = (json.loads(notes_file.read().decode("utf-8")) if notes_file
             else json.loads(SAMPLE_NOTES.read_text(encoding="utf-8")))
    site = SiteTracker(rates_path=RATES_PATH).run(notes, period_label=project_name)

    # --- Live workbook (bytes) ---
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        ElevateWorkbookBuilder(rates_path=RATES_PATH, gainsharing_result=gs).build(tmp.name)
        xlsx_bytes = Path(tmp.name).read_bytes()

    return {"gs": gs, "boq": boq, "site": site, "xlsx": xlsx_bytes}


# --------------------------------------------------------------------------- #
#  Render results
# --------------------------------------------------------------------------- #
if run:
    with st.spinner("Running the full pipeline… جارٍ التشغيل"):
        try:
            res = run_pipeline_inmemory()
        except Exception as exc:  # surface errors cleanly in the UI
            st.error(f"Pipeline error: {exc}")
            st.stop()
    st.session_state["res"] = res

res = st.session_state.get("res")
if res:
    gs = res["gs"]
    pool = gs.pool_df.iloc[0]
    site_agg = res["site"]["aggregate"]

    # Safety banner
    if gs.safety_disqualified:
        st.error("🟥 SAFETY GATE — Lost Time Injury recorded. Team DISQUALIFIED "
                 "from the performance bonus this period. / تم استبعاد الفريق.")

    st.subheader("Results | النتائج")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Net savings S", f"{pool['net_savings_S_egp']:,.0f} EGP")
    gate = pool["cash_gate_status"]
    c2.metric("Cash gate", gate, f"unlock {pool['unlock_ratio']:.2%}")
    c3.metric("Team pool (unlocked)", f"{pool['unlocked_pool_egp']:,.0f} EGP")
    c4.metric("Immediate 70%", f"{pool['immediate_70_egp']:,.0f} EGP")

    tabs = st.tabs(["💰 Gainsharing", "🧱 BOQ Audit", "📋 Site KPIs", "⬇️ Downloads"])

    # --- Gainsharing tab ---
    with tabs[0]:
        dist = gs.distribution_df
        st.dataframe(dist, width="stretch", hide_index=True)
        chart = dist[dist["gross_share_egp"] > 0][["name", "gross_share_egp"]]
        if not chart.empty:
            st.bar_chart(chart, x="name", y="gross_share_egp", color=GOLD)
        with st.expander("Pool & audit trail"):
            st.dataframe(gs.pool_df.T.astype(str), width="stretch")
            st.dataframe(gs.audit_df.astype(str), width="stretch", hide_index=True)

    # --- BOQ tab ---
    with tabs[1]:
        audited = res["boq"]["audited"]
        boq_rows = pd.DataFrame([{
            "item": a.item_code, "desc": a.description, "qty": a.quantity,
            "quoted": a.quoted_rate_egp, "target": a.target_rate_egp,
            "ppv_total": a.ppv_total_egp, "flags": ", ".join(a.flags),
        } for a in audited])
        st.dataframe(boq_rows, width="stretch", hide_index=True)
        st.markdown(res["boq"]["report_md"])

    # --- Site tab ---
    with tabs[2]:
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Avg PPC", f"{(site_agg['avg_ppc'] or 0):.1%}")
        s2.metric("Avg OEE", f"{(site_agg['avg_oee'] or 0):.1%}")
        s3.metric("Total NCRs", site_agg["total_ncr"])
        s4.metric("Total LTIs", site_agg["total_lti"])
        if site_agg["staff_hours"]:
            st.bar_chart(pd.Series(site_agg["staff_hours"], name="hours"))
        st.markdown(res["site"]["digest_md"])

    # --- Downloads tab ---
    with tabs[3]:
        st.download_button("⬇ Master workbook (.xlsx)", data=res["xlsx"],
                           file_name="UNITED_BROTHERS_ELEVATE_MASTER.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch")
        st.download_button("⬇ BOQ audit report (.md)",
                           data=res["boq"]["report_md"], file_name="boq_audit_report.md",
                           width="stretch")
        st.download_button("⬇ Site digest (.md)",
                           data=res["site"]["digest_md"], file_name="site_daily_digest.md",
                           width="stretch")
        st.download_button("⬇ Gainsharing result (.md)",
                           data=gs.summary(), file_name="gainsharing_result.md",
                           width="stretch")
else:
    st.info("Set your inputs on the left and the team above, then press "
            "**▶ Run PROJECT ELEVATE**. اضبط المدخلات ثم اضغط تشغيل.")
