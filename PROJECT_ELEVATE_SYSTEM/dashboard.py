#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py
============
United Brothers Co. / الاخوة المتحدين للمقاولات
PROJECT ELEVATE (Bulletproof Enterprise Edition)

Executive Web Dashboard (Streamlit + Plotly)
لوحة تحكم تنفيذية

A world-class, no-code executive dashboard for the whole PROJECT ELEVATE
pipeline. Enter the project financials and team, optionally upload a supplier
quote and site notes, click Run, and get:
  * Styled KPI hero tiles + an auto-generated Insights panel
  * Interactive Plotly visuals: savings→payout funnel, cash-gate gauge,
    per-member payout bars, and site-KPI gauges
  * BOQ audit and site digest views
  * One-click download of the branded master workbook and reports

Run locally:   streamlit run dashboard.py
Deploy free:   Streamlit Community Cloud (see docs/DEPLOY.md)

Python: 3.10+
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

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
NAVY2 = "#2F4B7C"
GOLD = "#D4AF37"
GOLD2 = "#B8942F"
GREEN = "#2E7D32"
AMBER = "#EF6C00"
CRIMSON = "#C62828"
INK = "#1B365D"

# --------------------------------------------------------------------------- #
#  Page setup & premium theme
# --------------------------------------------------------------------------- #
st.set_page_config(page_title="PROJECT ELEVATE — United Brothers Co.",
                   page_icon="🏗️", layout="wide", initial_sidebar_state="expanded")

st.markdown(f"""
<style>
  :root {{ --navy:{NAVY}; --gold:{GOLD}; }}
  .block-container {{ padding-top: 1.2rem; }}
  /* Header banner */
  .ub-header {{
    background: linear-gradient(120deg, {NAVY} 0%, {NAVY2} 100%);
    color: #fff; padding: 22px 28px; border-radius: 16px;
    box-shadow: 0 8px 24px rgba(27,54,93,.25);
    display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;
  }}
  .ub-header h1 {{ margin:0; font-size:27px; font-weight:800; letter-spacing:.3px; }}
  .ub-header .ar {{ color:{GOLD}; font-size:22px; font-weight:700; direction:rtl; }}
  .ub-header .sub {{ color:#d7e0ee; font-size:13.5px; margin-top:4px; }}
  .ub-badge {{ background:{GOLD}; color:{NAVY}; font-weight:800; padding:6px 14px;
    border-radius:999px; font-size:13px; white-space:nowrap; }}
  /* KPI metric tiles (style native st.metric) */
  div[data-testid="stMetric"] {{
    background:#fff; border:1px solid #e7ebf1; border-left:6px solid {NAVY};
    border-radius:14px; padding:14px 16px 10px 16px;
    box-shadow:0 2px 10px rgba(27,54,93,.06);
  }}
  div[data-testid="stMetric"] label p {{ color:#5b6b82 !important; font-weight:600; font-size:12.5px; }}
  div[data-testid="stMetricValue"] {{ font-size:24px; font-weight:800; color:{NAVY}; }}
  /* Verdict + insight callouts */
  .verdict {{ padding:14px 18px; border-radius:12px; font-weight:700; margin:6px 0 2px 0;
    display:flex; align-items:center; gap:10px; font-size:15.5px; }}
  .v-green {{ background:#E8F5E9; color:{GREEN}; border:1px solid #bfe3c3; }}
  .v-amber {{ background:#FFF3E0; color:{AMBER}; border:1px solid #f6d6ad; }}
  .v-red   {{ background:#FFEBEE; color:{CRIMSON}; border:1px solid #f2b8bd; }}
  .insight {{ background:#fff; border:1px solid #e7ebf1; border-left:5px solid {GOLD};
    border-radius:10px; padding:11px 14px; margin-bottom:9px; font-size:14px; color:#26364c;
    box-shadow:0 1px 6px rgba(27,54,93,.05); }}
  .insight b {{ color:{NAVY}; }}
  .sec-title {{ color:{NAVY}; font-weight:800; font-size:18px; margin:8px 0 2px 0; }}
  .muted {{ color:#6b7a90; font-size:13px; }}
</style>
""", unsafe_allow_html=True)

st.markdown(f"""
<div class="ub-header">
  <div>
    <h1>🏗️ {ENTITY_EN} &nbsp;·&nbsp; <span class="ar">{ENTITY_AR}</span></h1>
    <div class="sub">PROJECT ELEVATE — Gainsharing, KPI &amp; Operations Intelligence
    &nbsp;•&nbsp; لوحة ذكاء المشاركة في المكاسب والمؤشرات</div>
  </div>
  <div class="ub-badge">Bulletproof Enterprise Edition</div>
</div>
""", unsafe_allow_html=True)


def _load_config() -> dict:
    with RATES_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


CONFIG = _load_config()
COMMODITIES = list(CONFIG["material_escalation_index"].keys())


def egp(x: float) -> str:
    return f"{x:,.0f} EGP"


# --------------------------------------------------------------------------- #
#  Sidebar — inputs
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.markdown(f"### ⚙️ Inputs · المدخلات")
    st.markdown("**① Project financials · المالية**")
    project_name = st.text_input("Project · المشروع", "Ain Sokhna Industrial Warehouse")
    baseline = st.number_input("Baseline cost (EGP) · الأساسية",
                               min_value=0.0, value=12_000_000.0, step=100_000.0)
    actual = st.number_input("Actual cost (EGP) · الفعلية",
                             min_value=0.0, value=10_400_000.0, step=100_000.0)
    cash_pct = st.slider("Cash collected % · التحصيل", 0, 100, 82) / 100.0
    quality = st.slider("Quality factor · الجودة", 0.0, 1.0, 0.95, 0.01)
    commodity = st.selectbox("Escalation commodity · التصاعد", COMMODITIES,
                             index=COMMODITIES.index("steel_rebar")
                             if "steel_rebar" in COMMODITIES else 0)
    bad_debt = st.number_input("Bad debt (EGP) · ديون معدومة",
                               min_value=0.0, value=150_000.0, step=10_000.0)
    subk = st.number_input("Subcontractor value (EGP) · المقاول",
                           min_value=0.0, value=3_000_000.0, step=100_000.0)
    lti = st.number_input("Lost Time Injuries · إصابات", min_value=0, value=0, step=1)

    st.markdown("**② Data files · الملفات**")
    quote_file = st.file_uploader("Supplier quote (.txt)", type=["txt"])
    notes_file = st.file_uploader("Site notes (.json)", type=["json"])
    st.caption("Empty = built-in sample data.")

# Primary action (FIRST button in the document).
run = st.button("▶  Run PROJECT ELEVATE  ·  تشغيل", type="primary", width="stretch")

# --------------------------------------------------------------------------- #
#  Team editor
# --------------------------------------------------------------------------- #
st.markdown('<div class="sec-title">👷 Team &amp; individual KPIs · الفريق والمؤشرات</div>',
            unsafe_allow_html=True)
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
    fin = ProjectFinancials(
        project_name=project_name, baseline_cost_egp=baseline, actual_cost_egp=actual,
        cash_collected_pct=cash_pct, quality_factor=quality,
        escalation_commodity=commodity, bad_debt_egp=bad_debt,
        subcontractor_value_egp=subk, lost_time_injuries=int(lti),
    )
    gs = GainsharingCalculator(rates_path=RATES_PATH).run(fin, _members_from_df(team_df))
    quote_text = (quote_file.read().decode("utf-8") if quote_file
                  else SAMPLE_QUOTE.read_text(encoding="utf-8"))
    boq = BOQAuditor(rates_path=RATES_PATH).run(quote_text, supplier="Dashboard", project=project_name)
    notes = (json.loads(notes_file.read().decode("utf-8")) if notes_file
             else json.loads(SAMPLE_NOTES.read_text(encoding="utf-8")))
    site = SiteTracker(rates_path=RATES_PATH).run(notes, period_label=project_name)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        ElevateWorkbookBuilder(rates_path=RATES_PATH, gainsharing_result=gs).build(tmp.name)
        xlsx_bytes = Path(tmp.name).read_bytes()
    return {"gs": gs, "boq": boq, "site": site, "xlsx": xlsx_bytes}


# --------------------------------------------------------------------------- #
#  Chart builders (Plotly, navy/gold theme)
# --------------------------------------------------------------------------- #
def _base_layout(fig, height=300, title=""):
    fig.update_layout(
        height=height, title=title, title_font=dict(color=NAVY, size=15),
        margin=dict(l=10, r=10, t=40, b=10), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(color=INK, size=12),
        showlegend=False,
    )
    return fig


def funnel_chart(pool) -> go.Figure:
    fig = go.Figure(go.Funnel(
        y=["Net Savings (S)", "Team Pool 35%", "Unlocked (cash gate)", "Immediate 70%"],
        x=[pool["net_savings_S_egp"], pool["team_pool_raw_egp"],
           pool["unlocked_pool_egp"], pool["immediate_70_egp"]],
        textinfo="value+percent initial",
        marker={"color": [NAVY, NAVY2, GOLD, GOLD2]},
        connector={"line": {"color": "#cbd4e1"}},
    ))
    return _base_layout(fig, 320, "From savings to cash paid · من الوفورات إلى المدفوع")


def gauge_chart(value_pct, title, threshold, zones) -> go.Figure:
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=value_pct, number={"suffix": "%"},
        gauge={
            "axis": {"range": [0, 100]},
            "bar": {"color": NAVY},
            "steps": zones,
            "threshold": {"line": {"color": GOLD, "width": 4}, "thickness": 0.8,
                          "value": threshold},
        },
    ))
    return _base_layout(fig, 240, title)


CASH_ZONES = [{"range": [0, 75], "color": "#FFEBEE"},
              {"range": [75, 85], "color": "#FFF3E0"},
              {"range": [85, 100], "color": "#E8F5E9"}]
PPC_ZONES = [{"range": [0, 85], "color": "#FFF3E0"}, {"range": [85, 100], "color": "#E8F5E9"}]
OEE_ZONES = [{"range": [0, 95], "color": "#FFF3E0"}, {"range": [95, 100], "color": "#E8F5E9"}]


def member_bar(dist: pd.DataFrame) -> go.Figure:
    d = dist.sort_values("gross_share_egp")
    color_map = {"APPROVED_FULL": GREEN, "PENALTY_APPLIED": AMBER}
    colors = [color_map.get(s, CRIMSON) for s in d["status"]]
    fig = go.Figure(go.Bar(
        x=d["gross_share_egp"], y=d["name"], orientation="h",
        marker_color=colors, text=[egp(v) for v in d["gross_share_egp"]],
        textposition="outside",
    ))
    fig.update_layout(xaxis_title="Gross payout (EGP)")
    return _base_layout(fig, 300, "Payout by team member · التوزيع على الأعضاء")


# --------------------------------------------------------------------------- #
#  Insight generator
# --------------------------------------------------------------------------- #
def build_insights(gs, boq, site_agg) -> list[tuple[str, str]]:
    """Return list of (css_class, html_text) narrative insights."""
    out = []
    pool = gs.pool_df.iloc[0]
    dist = gs.distribution_df

    # Savings margin vs adjusted baseline.
    adj = pool["adjusted_baseline_egp"]
    if adj > 0:
        margin = (adj - pool["actual_egp"]) / adj
        out.append(("insight",
                    f"💰 Delivered <b>{margin:.1%}</b> under the inflation-adjusted baseline "
                    f"→ net savings <b>{egp(pool['net_savings_S_egp'])}</b> after quality &amp; bad-debt."))

    # Cash gate.
    gate = pool["cash_gate_status"]
    cash = pool["cash_collected_pct"]
    if gate == "FULL_UNLOCK":
        out.append(("insight", f"🟢 Cash at <b>{cash:.0%}</b> → <b>full pool unlock</b>. "
                               f"Immediate payout <b>{egp(pool['immediate_70_egp'])}</b>, "
                               f"held cushion {egp(pool['retained_30_egp'])}."))
    elif gate == "PARTIAL_UNLOCK":
        held_back = pool["team_pool_raw_egp"] - pool["unlocked_pool_egp"]
        out.append(("insight", f"🟠 Cash at <b>{cash:.0%}</b> (below 85%) → pool unlocked "
                               f"<b>{pool['unlock_ratio']:.1%}</b>; about <b>{egp(held_back)}</b> "
                               f"stays locked until collection reaches 85%."))
    else:
        out.append(("insight", f"🔴 Cash at <b>{cash:.0%}</b> (below 75%) → <b>100% holdback</b>, "
                               f"no payout this period until collection improves."))

    # Safety.
    if gs.safety_disqualified:
        out.append(("insight", "🔴 <b>Safety gate tripped</b> — a Lost Time Injury disqualifies the "
                               "whole team from the performance bonus this period."))

    # Eligibility breakdown.
    total = len(dist)
    approved = int((dist["status"] == "APPROVED_FULL").sum())
    penalty = int((dist["status"] == "PENALTY_APPLIED").sum())
    ineligible = int(dist["status"].str.startswith("INELIGIBLE").sum())
    if total:
        out.append(("insight", f"👷 <b>{approved}/{total}</b> members fully approved · "
                               f"<b>{penalty}</b> penalised (L&amp;D/scope) · "
                               f"<b>{ineligible}</b> ineligible (PPC &lt; 85%)."))
        paid = dist[dist["gross_share_egp"] > 0]
        if not paid.empty:
            top = paid.sort_values("gross_share_egp", ascending=False).iloc[0]
            out.append(("insight", f"🏅 Top earner: <b>{top['name']}</b> "
                                   f"({top['ld_badge']}) → <b>{egp(top['gross_share_egp'])}</b>."))

    # BOQ.
    audited = boq["audited"]
    total_ppv = sum(a.ppv_total_egp or 0 for a in audited)
    unapproved = sum(1 for a in audited if a.unapproved_scope_flag)
    if total_ppv > 0:
        worst = max((a for a in audited if a.ppv_total_egp), key=lambda a: a.ppv_total_egp, default=None)
        extra = f" — worst: <b>{worst.item_code}</b> at +{worst.variance_pct:.0%}" if worst and worst.variance_pct else ""
        out.append(("insight", f"🧱 Supplier quote is <b>{egp(total_ppv)} over</b> target{extra}. "
                               f"{unapproved} line(s) exceed the scope guardrail."))
    else:
        out.append(("insight", f"🧱 Supplier quote is <b>{egp(-total_ppv)} under</b> target — good buying."))

    # Site safety/PPC.
    if site_agg.get("avg_ppc") is not None:
        ppc = site_agg["avg_ppc"]
        flag = "✅ above" if ppc >= 0.85 else "⚠️ below"
        out.append(("insight", f"📋 Avg site PPC <b>{ppc:.1%}</b> — {flag} the 85% gate · "
                               f"{site_agg['total_ncr']} NCR(s), {site_agg['total_lti']} LTI(s)."))
    return out


# --------------------------------------------------------------------------- #
#  Run & render
# --------------------------------------------------------------------------- #
if run:
    with st.spinner("Running the full pipeline… جارٍ التشغيل"):
        try:
            st.session_state["res"] = run_pipeline_inmemory()
        except Exception as exc:
            st.error(f"Pipeline error: {exc}")
            st.stop()

res = st.session_state.get("res")

if not res:
    st.markdown("")
    st.info("👈 Set your inputs and team, then press **▶ Run PROJECT ELEVATE**. "
            "اضبط المدخلات ثم اضغط تشغيل.")
    st.stop()

gs = res["gs"]
pool = gs.pool_df.iloc[0]
site_agg = res["site"]["aggregate"]

# --- Verdict banner ---
if gs.safety_disqualified:
    st.markdown('<div class="verdict v-red">🟥 SAFETY DISQUALIFICATION — Lost Time Injury recorded; '
                'team removed from the performance bonus this period · تم استبعاد الفريق</div>',
                unsafe_allow_html=True)
elif pool["cash_gate_status"] == "FULL_UNLOCK":
    st.markdown(f'<div class="verdict v-green">🟩 FULL PAYOUT APPROVED — '
                f'{egp(pool["immediate_70_egp"])} paid immediately · دفع كامل معتمد</div>',
                unsafe_allow_html=True)
elif pool["cash_gate_status"] == "PARTIAL_UNLOCK":
    st.markdown(f'<div class="verdict v-amber">🟧 PARTIAL PAYOUT — cash gate at '
                f'{pool["unlock_ratio"]:.0%}; {egp(pool["immediate_70_egp"])} released · دفع جزئي</div>',
                unsafe_allow_html=True)
else:
    st.markdown('<div class="verdict v-red">🟥 HOLDBACK — cash below 75%; no payout this period · '
                'حجز كامل</div>', unsafe_allow_html=True)

# --- KPI hero tiles ---
k = st.columns(6)
k[0].metric("Net Savings (S)", egp(pool["net_savings_S_egp"]))
k[1].metric("Team Pool (unlocked)", egp(pool["unlocked_pool_egp"]))
k[2].metric("Immediate 70%", egp(pool["immediate_70_egp"]))
k[3].metric("Retained 30%", egp(pool["retained_30_egp"]))
k[4].metric("Cash Gate", pool["cash_gate_status"].replace("_", " ").title(),
            f"{pool['unlock_ratio']:.0%} unlock")
avg_ppc = site_agg.get("avg_ppc") or 0
k[5].metric("Avg PPC", f"{avg_ppc:.0%}",
            "Safety ✗" if gs.safety_disqualified else "Safety ✓", delta_color="off")

# --- Tabs ---
tabs = st.tabs(["📊 Executive", "💰 Team payout", "🧱 BOQ Audit", "📋 Site KPIs", "⬇️ Downloads"])

# Executive
with tabs[0]:
    left, right = st.columns([3, 2])
    with left:
        st.markdown('<div class="sec-title">Key insights · أبرز المؤشرات</div>', unsafe_allow_html=True)
        for cls, html in build_insights(gs, res["boq"], site_agg):
            st.markdown(f'<div class="{cls}">{html}</div>', unsafe_allow_html=True)
    with right:
        st.plotly_chart(gauge_chart(pool["cash_collected_pct"] * 100,
                        "Cash collected vs 85% gate", 85, CASH_ZONES), width="stretch", key="g_cash")
    c1, c2 = st.columns(2)
    c1.plotly_chart(funnel_chart(pool), width="stretch", key="funnel")
    c2.plotly_chart(member_bar(gs.distribution_df), width="stretch", key="mbar_exec")

# Team payout
with tabs[1]:
    show = gs.distribution_df[[
        "name", "role", "ld_badge", "ppc", "base_share_egp", "perf_share_egp",
        "gross_share_egp", "immediate_70_egp", "retained_30_egp", "status", "notes"]]
    st.dataframe(show, width="stretch", hide_index=True)
    st.plotly_chart(member_bar(gs.distribution_df), width="stretch", key="mbar_team")
    with st.expander("Pool cascade & audit trail · التدقيق"):
        st.dataframe(gs.pool_df.T.astype(str), width="stretch")
        st.dataframe(gs.audit_df.astype(str), width="stretch", hide_index=True)

# BOQ
with tabs[2]:
    audited = res["boq"]["audited"]
    boq_rows = pd.DataFrame([{
        "item": a.item_code, "description": a.description, "qty": a.quantity,
        "quoted": a.quoted_rate_egp, "target": a.target_rate_egp,
        "ppv_total": a.ppv_total_egp, "flags": ", ".join(a.flags),
    } for a in audited])
    tot_ppv = boq_rows["ppv_total"].fillna(0).sum()
    m = st.columns(3)
    m[0].metric("Total PPV", egp(tot_ppv))
    m[1].metric("Overspend lines", int((boq_rows["ppv_total"].fillna(0) > 0).sum()))
    m[2].metric("Unapproved scope", sum(1 for a in audited if a.unapproved_scope_flag))
    st.dataframe(boq_rows, width="stretch", hide_index=True)
    with st.expander("Full BOQ audit report"):
        st.markdown(res["boq"]["report_md"])

# Site KPIs
with tabs[3]:
    g = st.columns(2)
    g[0].plotly_chart(gauge_chart((site_agg.get("avg_ppc") or 0) * 100,
                      "Avg PPC vs 85%", 85, PPC_ZONES), width="stretch", key="g_ppc")
    g[1].plotly_chart(gauge_chart((site_agg.get("avg_oee") or 0) * 100,
                      "Avg OEE vs 95%", 95, OEE_ZONES), width="stretch", key="g_oee")
    s = st.columns(3)
    s[0].metric("Total NCRs", site_agg["total_ncr"])
    s[1].metric("Total LTIs", site_agg["total_lti"])
    s[2].metric("Sites reported", len(res["site"]["logs"]))
    if site_agg["staff_hours"]:
        st.bar_chart(pd.Series(site_agg["staff_hours"], name="hours"))
    with st.expander("CEO daily digest"):
        st.markdown(res["site"]["digest_md"])

# Downloads
with tabs[4]:
    st.markdown('<div class="sec-title">Export · تصدير</div>', unsafe_allow_html=True)
    st.download_button("⬇ Master workbook (.xlsx)", data=res["xlsx"],
                       file_name="UNITED_BROTHERS_ELEVATE_MASTER.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       width="stretch")
    st.download_button("⬇ BOQ audit report (.md)", data=res["boq"]["report_md"],
                       file_name="boq_audit_report.md", width="stretch")
    st.download_button("⬇ Site digest (.md)", data=res["site"]["digest_md"],
                       file_name="site_daily_digest.md", width="stretch")
    st.download_button("⬇ Gainsharing result (.md)", data=gs.summary(),
                       file_name="gainsharing_result.md", width="stretch")
