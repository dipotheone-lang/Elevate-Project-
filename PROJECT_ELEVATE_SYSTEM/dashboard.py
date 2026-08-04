#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dashboard.py
============
United Brothers Co. / الاخوة المتحدين للمقاولات
PROJECT ELEVATE — Gainsharing & Operations Intelligence

Executive web dashboard implementing the Claude Design prototype
(`ELEVATE Dashboard.dc.html` + PORT_GUIDE): brick-red/navy/gold palette,
IBM Plex type, dark top bar with project/period/role switchers and EN/ع toggle,
splash, top-risk + gate strips (with the LTI reconciliation the design caught),
Portfolio / Executive / Team payout / BOQ audit / Site KPIs / Downloads, roles,
and read-only closed-period summaries.

Charts are HTML/CSS (no Plotly font/DPI drift on a projector), per the PORT_GUIDE.

Run locally:  streamlit run dashboard.py
Deploy:       Streamlit Community Cloud (see docs/DEPLOY.md)
Python: 3.10+
"""

from __future__ import annotations

import base64
import json
import sys
import tempfile
from pathlib import Path

import streamlit as st
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from boq_auditor import BOQAuditor  # noqa: E402
from site_tracker import SiteTracker  # noqa: E402
from gainsharing_calculator import (  # noqa: E402
    GainsharingCalculator, ProjectFinancials, TeamMember,
)
from export_excel_template import ElevateWorkbookBuilder  # noqa: E402
import portfolio_data as P  # noqa: E402

RATES_PATH = HERE / "target_rates.json"
SAMPLE_QUOTE = HERE / "sample_inputs" / "supplier_quote.txt"
SAMPLE_NOTES = HERE / "sample_inputs" / "site_notes.json"
LOGO_PATH = HERE / "assets" / "ub-logo-128.png"

st.set_page_config(page_title="PROJECT ELEVATE — United Brothers Co.",
                   page_icon="🏗️", layout="wide", initial_sidebar_state="collapsed")


@st.cache_data
def _logo_uri() -> str:
    try:
        return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()
    except Exception:
        return ""


LOGO = _logo_uri()

# --------------------------------------------------------------------------- #
#  Session state
# --------------------------------------------------------------------------- #
ss = st.session_state
ss.setdefault("lang", "en")
ss.setdefault("role", "exec")
ss.setdefault("proj", "p1")
ss.setdefault("per", "jul")
ss.setdefault("cap", False)
ss.setdefault("big", False)
ss.setdefault("ran", False)

EN = ss["lang"] == "en"
DIR = "rtl" if not EN else "ltr"


def T(en: str, ar: str) -> str:
    return en if EN else ar


# --------------------------------------------------------------------------- #
#  Theme (IBM Plex + corrected palette)
# --------------------------------------------------------------------------- #
ZOOM = "zoom:1.16;" if ss["big"] else ""
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Sans+Arabic:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');
:root {{ --navy:{P.NAVY}; --gold:{P.GOLD}; --brick:{P.BRICK}; }}
html, body, [class*="css"], .stApp {{ font-family:'IBM Plex Sans','IBM Plex Sans Arabic',system-ui,sans-serif; }}
.stApp {{ background:{P.PAGE_BG}; }}
.block-container {{ padding:0 0 60px 0 !important; max-width:1460px; {ZOOM} }}
.mono {{ font-family:'IBM Plex Mono',monospace; font-variant-numeric:tabular-nums; }}
[data-testid="stHeader"] {{ background:transparent; }}
/* KPI tiles */
div[data-testid="stMetric"] {{ background:{P.CARD}; border:1px solid {P.BORDER}; border-top:3px solid {P.NAVY};
  border-radius:12px; padding:13px 15px 9px; box-shadow:0 1px 6px rgba(27,54,93,.05); }}
div[data-testid="stMetric"] label p {{ color:{P.MUTED2}!important; font-weight:600; font-size:10.5px; text-transform:uppercase; letter-spacing:.7px; }}
div[data-testid="stMetricValue"] {{ font-size:22px; font-weight:600; color:{P.NAVY}; letter-spacing:-.5px; }}
/* tabs */
button[data-baseweb="tab"] {{ font-weight:600!important; font-size:13px!important; color:#7C8CA3!important; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color:{P.NAVY}!important; }}
div[data-baseweb="tab-highlight"], div[data-baseweb="tab-border"] {{ background:{P.NAVY}!important; }}
.stTabs [data-baseweb="tab-list"] {{ gap:4px; }}
/* generic card blocks */
.ubwrap {{ padding:20px 26px 0; }}
</style>
<div dir="{DIR}"></div>
""", unsafe_allow_html=True)


def money(n) -> str:
    return P.fmt(n)


# --------------------------------------------------------------------------- #
#  Engine — live scenario (Ain Sokhna · Jul 2026), cached
# --------------------------------------------------------------------------- #
@st.cache_data(show_spinner=False)
def run_engine() -> dict:
    fin = ProjectFinancials(
        project_name="Ain Sokhna Industrial Warehouse",
        baseline_cost_egp=12_000_000.0, actual_cost_egp=10_400_000.0,
        cash_collected_pct=0.82, quality_factor=0.95, escalation_commodity="steel_rebar",
        bad_debt_egp=150_000.0, subcontractor_value_egp=3_000_000.0, lost_time_injuries=0)
    members = [
        TeamMember("Ahmed Fathy", "Site Manager", time_weight=1.0, ld_badge="Level 3",
                   ppc=0.92, equipment_oee=0.97, vo_settlement_days=5, value_engineering_savings_egp=200_000),
        TeamMember("Mona Adel", "QA/QC Engineer", time_weight=0.8, ld_badge="Level 2", ppc=0.88, ld_sla_met=False),
        TeamMember("Khaled Samir", "Foreman", time_weight=1.0, ld_badge="Level 1", ppc=0.70),
        TeamMember("Sara Nabil", "Planner", time_weight=0.5, ld_badge="Level 2", ppc=0.90,
                   resigning_clean_handover=True, kaizen_points=2)]
    gs = GainsharingCalculator(rates_path=RATES_PATH).run(fin, members)
    boq = BOQAuditor(rates_path=RATES_PATH).run(SAMPLE_QUOTE.read_text(encoding="utf-8"),
                                                supplier="Delta Industrial Supplies", project="Ain Sokhna")
    site = SiteTracker(rates_path=RATES_PATH).run(json.loads(SAMPLE_NOTES.read_text(encoding="utf-8")))
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        ElevateWorkbookBuilder(rates_path=RATES_PATH, gainsharing_result=gs).build(tmp.name)
        xlsx = Path(tmp.name).read_bytes()
    return {"gs": gs, "boq": boq, "site": site, "xlsx": xlsx}


# --------------------------------------------------------------------------- #
#  SPLASH — the Run button MUST be the first st.button (smoke test)
# --------------------------------------------------------------------------- #
if not ss["ran"]:
    st.markdown(f"""
    <div style="min-height:78vh;display:flex;flex-direction:column;align-items:center;justify-content:center;
      background:radial-gradient(120% 100% at 50% 0%,{P.NAVY} 0%,{P.NAVY_DEEP} 60%,#0C1D33 100%);
      border-radius:0 0 20px 20px;padding:60px 0;margin-bottom:10px">
      <div style="width:104px;height:104px;border-radius:22px;background:{P.CREAM};display:flex;align-items:center;
        justify-content:center;box-shadow:0 18px 50px rgba(0,0,0,.35);overflow:hidden">
        <img src="{LOGO}" style="width:92px;height:92px;object-fit:contain"></div>
      <div style="height:2px;width:64px;background:{P.GOLD};margin:30px 0 22px"></div>
      <div style="font-size:11px;font-weight:600;letter-spacing:3.4px;color:{P.GOLD};text-transform:uppercase">Project Elevate</div>
      <h1 style="margin:12px 0 0;font-size:34px;font-weight:600;color:#fff;text-align:center">
        {T("Gainsharing &amp; Operations Intelligence","ذكاء المشاركة في المكاسب والعمليات")}</h1>
      <p style="margin:14px 0 0;max-width:520px;text-align:center;font-size:14px;line-height:1.6;color:#8CA3C2">
        {T("United Brothers Co. · الاخوة المتحدين للمقاولات — four active projects, one governance engine. Open the console to review the live period.",
           "الاخوة المتحدين للمقاولات — أربعة مشاريع نشطة ومحرك حوكمة واحد. افتح لوحة التحكم لمراجعة الفترة الحية.")}</p>
    </div>""", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([2, 1, 2])
    with c2:
        if st.button(T("▶  Open the console", "▶  فتح لوحة التحكم"), type="primary", width="stretch"):
            ss["ran"] = True
            st.rerun()
    st.stop()

RES = run_engine()
gs = RES["gs"]
pool = gs.pool_df.iloc[0]
dist = gs.distribution_df
site_agg = RES["site"]["aggregate"]
audited = RES["boq"]["audited"]

proj = P.get_project(ss["proj"])
per_row = P.get_period_row(ss["proj"], ss["per"])
LIVE = ss["proj"] == "p1" and ss["per"] == "jul"
role = ss["role"]
scope_portfolio = role == "exec"

# --------------------------------------------------------------------------- #
#  TOP BAR (logo + name + switchers + role + language + projector + re-run)
# --------------------------------------------------------------------------- #
st.markdown(f"""
<div style="display:flex;align-items:center;gap:16px;padding:13px 26px;background:{P.NAVY_DEEP};
  border-bottom:3px solid {P.GOLD};border-radius:0 0 4px 4px" dir="{DIR}">
  <div style="width:40px;height:40px;border-radius:9px;background:{P.CREAM};display:flex;align-items:center;
    justify-content:center;overflow:hidden;flex:none"><img src="{LOGO}" style="width:38px;height:38px;object-fit:contain"></div>
  <div style="display:flex;flex-direction:column;gap:1px">
    <div style="display:flex;align-items:baseline;gap:9px">
      <span style="font-size:15px;font-weight:600;color:#fff">United Brothers Co.</span>
      <span style="font-size:13px;font-weight:500;color:{P.GOLD};direction:rtl">الاخوة المتحدين للمقاولات</span>
    </div>
    <div style="font-size:11px;font-weight:500;color:#8CA3C2;letter-spacing:.4px;text-transform:uppercase">
      Project Elevate <span style="color:#3F587C;padding:0 6px">/</span>
      {T("Gainsharing &amp; Operations Intelligence","ذكاء المشاركة في المكاسب والعمليات")}</div>
  </div>
</div>""", unsafe_allow_html=True)

# Interactive control row (Streamlit widgets styled to sit under the bar).
tb = st.columns([3, 2.4, 2, 1.4, 1.1, 1.1])
with tb[0]:
    proj_names = {p["id"]: P.get_project(p["id"])[("name" if EN else "nameAr")] for p in P.PROJECTS}
    sel = st.selectbox(T("Project", "المشروع"), list(proj_names), index=[p["id"] for p in P.PROJECTS].index(ss["proj"]),
                       format_func=lambda k: proj_names[k], label_visibility="collapsed",
                       disabled=not scope_portfolio)
    if sel != ss["proj"]:
        ss["proj"] = sel; st.rerun()
with tb[1]:
    per_keys = [p["k"] for p in P.PERIODS]
    selp = st.selectbox(T("Period", "الفترة"), per_keys, index=per_keys.index(ss["per"]),
                        format_func=lambda k: P.period_label(k, ss["lang"]), label_visibility="collapsed")
    if selp != ss["per"]:
        ss["per"] = selp; st.rerun()
with tb[2]:
    role_keys = [r["k"] for r in P.ROLES]
    selr = st.selectbox("role", role_keys, index=role_keys.index(role),
                        format_func=lambda k: next(r[("en" if EN else "ar")] for r in P.ROLES if r["k"] == k),
                        label_visibility="collapsed")
    if selr != role:
        ss["role"] = selr; st.rerun()
with tb[3]:
    lang_sel = st.selectbox("lang", ["en", "ar"], index=0 if EN else 1,
                            format_func=lambda k: "English" if k == "en" else "العربية",
                            label_visibility="collapsed")
    if lang_sel != ss["lang"]:
        ss["lang"] = lang_sel; st.rerun()
with tb[4]:
    big = st.toggle(T("Projector", "عرض"), value=ss["big"])
    if big != ss["big"]:
        ss["big"] = big; st.rerun()
with tb[5]:
    if st.button(T("Re-run", "إعادة"), width="stretch"):
        run_engine.clear(); ss["ran"] = False; st.rerun()

# Scope note when a non-live selection is chosen.
if not LIVE:
    st.markdown(f"""<div class="ubwrap"><div style="display:flex;align-items:center;gap:10px;padding:11px 15px;
      background:#FBF3DE;border:1px solid #EBD9A8;border-radius:10px;font-size:12.5px;color:#8A6A15" dir="{DIR}">
      <span style="font-weight:600">{proj['code']} · {P.period_label(ss['per'], ss['lang'])}</span>
      <span>{T("Live detail is wired for Ain Sokhna · Jul 2026. Other selections show the read-only closed-period summary.",
               "التفاصيل الحية مرتبطة بالعين السخنة · يوليو ٢٠٢٦. الاختيارات الأخرى تعرض ملخص الفترة المغلقة للقراءة فقط.")}</span>
    </div></div>""", unsafe_allow_html=True)

st.markdown('<div class="ubwrap">', unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
#  Reusable HTML fragments
# --------------------------------------------------------------------------- #
def chip(vkey: str, big=False) -> str:
    d = P.VERDICTS[vkey]
    pad = "5px 11px" if big else "3px 8px"
    fs = "12px" if big else "11px"
    return (f'<span style="display:inline-flex;align-items:center;border-radius:6px;padding:{pad};'
            f'font-weight:600;font-size:{fs};color:{d["c"]};background:{d["f"]}">{d[("en" if EN else "ar")]}</span>')


def card(html: str) -> str:
    return f'<div style="background:{P.CARD};border:1px solid {P.BORDER};border-radius:14px">{html}</div>'


# LTI reconciliation (the defect the design surfaced).
site_lti = site_agg["total_lti"]
lti_unreconciled = LIVE and site_lti > 0 and not gs.safety_disqualified

# --------------------------------------------------------------------------- #
#  Top-risk + gate strips (live, exec/mgr)
# --------------------------------------------------------------------------- #
if LIVE and role != "member" and lti_unreconciled:
    st.markdown(f"""<div style="display:flex;gap:10px;margin-bottom:18px" dir="{DIR}">
      <div style="flex:1;background:#fff;border:1px solid {P.BORDER};border-inline-start:4px solid {P.BRICK};
        border-radius:12px;padding:13px 16px">
        <div style="font-size:10.5px;font-weight:600;letter-spacing:1.2px;color:{P.BRICK};text-transform:uppercase;margin-bottom:3px">
          {T("Top risk · act today","أعلى مخاطرة · تصرّف اليوم")}</div>
        <div style="font-size:13.5px;color:#3A2320;line-height:1.5">
          {T(f"<b style='color:{P.BRICK}'>1 Lost Time Injury</b> is in the Ain Sokhna site log but the safety gate is still 0. "
             f"Reconcile it — if confirmed, the entire <b>{money(pool['unlocked_pool_egp'])} EGP</b> team pool is disqualified.",
             f"<b style='color:{P.BRICK}'>إصابة وقت ضائع واحدة</b> مسجّلة في تقرير العين السخنة وبوابة السلامة على صفر. "
             f"راجع البيانات — وإذا تأكدت يُستبعد كامل مجمع الفريق <b>{money(pool['unlocked_pool_egp'])} جنيه</b>.")}</div>
        <div style="margin-top:8px;font-size:11.5px;font-weight:600;color:{P.BRICK}">
          {T("HSE Manager · close by 07 Aug, before payroll cut-off","مدير السلامة · الإغلاق قبل ٧ أغسطس قبل موعد الرواتب")}</div>
      </div>
      <div style="width:300px;flex:none;background:#fff;border:1px solid {P.BORDER};border-radius:12px;padding:11px 14px">
        <div style="font-size:10.5px;font-weight:600;letter-spacing:1.2px;color:{P.MUTED};text-transform:uppercase;margin-bottom:9px">{T("Gates","البوابات")}</div>
        <div style="display:flex;align-items:center;gap:9px;padding:8px 10px;background:{P.BRICK_FILL};border-radius:8px;margin-bottom:8px">
          <span style="width:9px;height:9px;border-radius:50%;background:{P.BRICK}"></span>
          <span style="font-size:12.5px;font-weight:600;flex:1;color:{P.BRICK}">{T("Safety · disqualifying","السلامة · مستبعدة")}</span>
          <span class="mono" style="font-weight:600;color:{P.BRICK}">1 LTI</span></div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
          <div><div style="font-size:10.5px;font-weight:600;color:{P.MUTED2}">{T("Cash","التحصيل")}</div><div class="mono" style="font-weight:600;color:{P.AMBER}">82%</div></div>
          <div><div style="font-size:10.5px;font-weight:600;color:{P.MUTED2}">PPC</div><div class="mono" style="font-weight:600;color:{P.AMBER}">84%</div></div>
          <div><div style="font-size:10.5px;font-weight:600;color:{P.MUTED2}">{T("Scope","النطاق")}</div><div class="mono" style="font-weight:600;color:{P.AMBER}">4</div></div>
        </div>
      </div></div>""", unsafe_allow_html=True)

# --------------------------------------------------------------------------- #
#  Tabs (role-scoped)
# --------------------------------------------------------------------------- #
TAB_LABELS = {
    "pf": T("Portfolio", "المحفظة"), "exec": T("Executive", "الملخص التنفيذي"),
    "team": T("Team payout", "توزيع الفريق"), "boq": T("BOQ audit", "تدقيق المقايسة"),
    "site": T("Site KPIs", "مؤشرات الموقع"), "dl": T("Downloads", "التنزيلات"),
}
tab_keys = P.ROLE_TABS[role]
tabs = st.tabs([TAB_LABELS[k] for k in tab_keys])
tab = dict(zip(tab_keys, tabs))


# ============================ PORTFOLIO ==================================== #
if "pf" in tab:
    with tab["pf"]:
        tot = P.portfolio_totals(ss["per"])
        # Hero + blocked-by-cause
        blocked_rows_html = ""
        for br in tot["blocked_rows"]:
            c = P.CAUSE[br["cause"]]
            fore = P.unlock_forecast(br["cause"], br["row"]["b"], (br["row"]["c"] or 0) / 100)
            unlock = ("+" + money(fore["recoverable"]) if fore["recoverable"] else T("not cash", "ليست نقدية"))
            pts = (f"+{fore['points_needed']:.0f} pts" if fore["points_needed"] else "—")
            blocked_rows_html += f"""<div style="display:flex;align-items:center;gap:13px;padding:12px 16px;border-top:1px solid #EDF1F6">
              <span class="mono" style="font-size:15px;font-weight:600;color:{c['c']};width:96px">{money(br['row']['b'])}</span>
              <span style="flex:1;min-width:0;display:flex;flex-direction:column;gap:2px">
                <span style="font-size:11px;font-weight:600;color:{c['c']}">{c[('en' if EN else 'ar')]}</span>
                <span style="font-size:12.5px;font-weight:600;color:{P.NAVY};white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{P.get_project(br['project']['id'])[('name' if EN else 'nameAr')]}</span></span>
              <span style="text-align:end;flex:none">
                <div style="font-size:12px;font-weight:600;color:{P.NAVY}">{c[('owner' if EN else 'ownerAr')]} · {c[('due' if EN else 'dueAr')]}</div>
                <div class="mono" style="font-size:11px;color:{P.MUTED2}">{unlock} · {pts}</div></span></div>"""
        st.markdown(f"""<div style="display:flex;gap:14px;margin-bottom:18px" dir="{DIR}">
          <div style="width:452px;flex:none;background:linear-gradient(135deg,{P.NAVY} 0%,{P.NAVY_DEEP} 100%);border-radius:16px;padding:22px 24px">
            <div style="font-size:11.5px;font-weight:600;letter-spacing:1.6px;color:#8CA3C2;text-transform:uppercase;margin-bottom:6px">
              {T("Released across the portfolio","المصروف على مستوى المحفظة")}</div>
            <div style="display:flex;align-items:baseline;gap:11px">
              <span class="mono" style="font-size:50px;font-weight:600;color:#fff;letter-spacing:-2px">{money(tot['released'])}</span>
              <span style="font-size:17px;font-weight:500;color:{P.GOLD}">EGP</span></div>
            <div style="display:flex;margin-top:18px;border-top:1px solid #2A4467;padding-top:15px;gap:14px">
              <div style="flex:1"><div style="font-size:10px;font-weight:600;letter-spacing:1px;color:#7B93B4;text-transform:uppercase;margin-bottom:4px">{T("Net savings","صافي الوفورات")}</div><div class="mono" style="font-size:18px;font-weight:600;color:#DCE5F0">{money(tot['savings'])}</div></div>
              <div style="width:1px;background:#2A4467"></div>
              <div style="flex:1"><div style="font-size:10px;font-weight:600;letter-spacing:1px;color:#7B93B4;text-transform:uppercase;margin-bottom:4px">{T("Retained","المحتجز")}</div><div class="mono" style="font-size:18px;font-weight:600;color:#DCE5F0">{money(tot['retained'])}</div></div>
              <div style="width:1px;background:#2A4467"></div>
              <div style="flex:1"><div style="font-size:10px;font-weight:600;letter-spacing:1px;color:#7B93B4;text-transform:uppercase;margin-bottom:4px">{T("Paying","تدفع")}</div><div class="mono" style="font-size:18px;font-weight:600;color:#DCE5F0">{tot['paying']} / 4</div></div>
            </div></div>
          <div style="flex:1;min-width:0;background:#fff;border:1px solid {P.BORDER};border-radius:16px;overflow:hidden">
            <div style="display:flex;align-items:baseline;gap:11px;padding:15px 18px 12px">
              <span style="font-size:13px;font-weight:600;color:{P.NAVY}">{T("Blocked money, by cause","الأموال المحجوزة بحسب السبب")}</span>
              <span class="mono" style="font-size:15px;font-weight:600;color:{P.BRICK}">{money(tot['blocked'])}</span>
              <span style="flex:1"></span>
              <span style="font-size:11px;color:{P.MUTED2}">{T(f"{len(tot['blocked_rows'])} of 4 · one owner each", f"{len(tot['blocked_rows'])} من ٤ · لكل سبب مسؤول")}</span></div>
            {blocked_rows_html}</div></div>""", unsafe_allow_html=True)

        # Project table with sparklines
        rows = ""
        for p in P.PROJECTS:
            r = P.get_period_row(p["id"], ss["per"])
            v = P.VERDICTS[r["v"]]
            dtxt, dcol = P.delta_vs_prior(p, ss["per"], ss["lang"])
            spark = P.spark_points(p)
            barw = max(2, (r["r"] / P.MAX_RELEASED) * 100) if r["r"] else 0
            cashcol = (P.GREEN if (r["c"] or 0) >= 85 else P.AMBER if (r["c"] or 0) >= 75 else P.BRICK) if r["c"] else "#A8B4C6"
            sel = p["id"] == ss["proj"]
            rows += f"""<div style="display:flex;align-items:center;gap:14px;padding:13px 18px;border-top:1px solid #EDF1F6;
              border-inline-start:3px solid {P.NAVY if sel else 'transparent'};background:{'#F6F8FB' if sel else '#fff'}">
              <span style="flex:1;min-width:0;display:flex;flex-direction:column;gap:2px">
                <span style="font-size:13.5px;font-weight:600;color:{P.NAVY}">{P.get_project(p['id'])[('name' if EN else 'nameAr')]}</span>
                <span style="font-size:11.5px;color:{P.MUTED2}">{p['code']} · {P.get_project(p['id'])[('region' if EN else 'regionAr')]}</span></span>
              <span style="width:130px;flex:none">{chip(r['v'])}</span>
              <span style="width:150px;flex:none">
                <span class="mono" style="font-size:13.5px;font-weight:600;color:{P.NAVY}">{money(r['r'])}</span>
                <span style="display:block;height:9px;border-radius:3px;background:#EDF1F6;margin-top:4px"><span style="display:block;height:9px;border-radius:3px;background:{v['c']};width:{barw}%"></span></span></span>
              <span style="width:70px;flex:none"><svg width="64" height="22" style="display:block;overflow:visible"><polyline points="{spark}" style="fill:none;stroke:{P.NAVY2 if r['r'] else P.BRICK};stroke-width:1.6;stroke-linejoin:round"></polyline></svg></span>
              <span style="width:72px;flex:none;text-align:end" class="mono"><span style="font-size:12.5px;font-weight:600;color:{dcol}">{dtxt}</span></span>
              <span style="width:56px;flex:none;text-align:end" class="mono"><span style="font-size:13px;font-weight:600;color:{cashcol}">{(str(r['c'])+'%') if r['c'] else '—'}</span></span>
              <span style="width:56px;flex:none;text-align:end" class="mono" style="color:{P.MUTED}">{(str(r['p'])+'%') if r['p'] else '—'}</span>
              <span style="width:60px;flex:none;text-align:end" class="mono" style="color:{P.MUTED}">{p['paid']}/{p['members']}</span></div>"""
        st.markdown(f"""<div style="background:#fff;border:1px solid {P.BORDER};border-radius:14px;overflow:hidden;margin-bottom:18px" dir="{DIR}">
          <div style="display:flex;align-items:center;gap:14px;padding:9px 18px;background:#F6F8FB;border-bottom:1px solid {P.BORDER};font-size:10.5px;font-weight:600;letter-spacing:.9px;color:{P.MUTED};text-transform:uppercase">
            <span style="flex:1">{T("Project","المشروع")}</span><span style="width:130px">{T("Verdict","القرار")}</span>
            <span style="width:150px">{T("Released","المصروف")}</span><span style="width:70px">{T("Trend","الاتجاه")}</span>
            <span style="width:72px;text-align:end">{T("vs prior","مقابل السابق")}</span><span style="width:56px;text-align:end">{T("Cash","تحصيل")}</span>
            <span style="width:56px;text-align:end">PPC</span><span style="width:60px;text-align:end">{T("Paid","مدفوع")}</span></div>
          {rows}</div>""", unsafe_allow_html=True)

        # Period history matrix
        head = "".join(f'<span style="width:108px;flex:none;font-size:10.5px;font-weight:600;letter-spacing:.9px;color:{P.GOLD2 if pk["k"]=="aug" else P.MUTED};text-transform:uppercase;padding-inline-start:11px">{pk[("en" if EN else "ar")]}</span>' for pk in P.PERIODS)
        matrix = ""
        for p in P.PROJECTS:
            cells = ""
            for x in p["periods"]:
                d = P.VERDICTS[x["v"]]
                selc = p["id"] == ss["proj"] and x["k"] == ss["per"]
                amt = P.fmt(x["r"]) if x["r"] is not None else T("open", "مفتوحة")
                cells += f"""<span style="width:108px;flex:none;display:flex;flex-direction:column;gap:3px;padding:8px 11px;border-radius:9px;border:1.5px solid {P.NAVY if selc else 'transparent'};background:{d['f']}">
                  <span class="mono" style="font-size:12.5px;font-weight:600;color:{d['c']}">{amt}</span>
                  <span style="font-size:9.5px;font-weight:600;color:{d['c']};text-transform:uppercase;letter-spacing:.5px">{d[('s' if EN else 'sa')]}</span></span>"""
            matrix += f"""<div style="display:flex;align-items:stretch;gap:9px;margin-bottom:8px">
              <span style="flex:1;min-width:0;display:flex;flex-direction:column;justify-content:center;gap:2px;padding-inline-end:10px">
                <span style="font-size:12.5px;font-weight:600;color:{P.NAVY}">{P.get_project(p['id'])[('name' if EN else 'nameAr')]}</span>
                <span style="font-size:11px;color:{P.MUTED2}">{T('handover','التسليم')} {P.HANDOVER[p['id']][('en' if EN else 'ar')]}</span></span>{cells}</div>"""
        st.markdown(f"""<div style="background:#fff;border:1px solid {P.BORDER};border-radius:14px;overflow:hidden" dir="{DIR}">
          <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid {P.BORDER}">
            <h2 style="margin:0;font-size:14.5px;font-weight:600;color:{P.NAVY}">{T("Period history","سجل الفترات")}</h2>
            <span style="font-size:11.5px;color:{P.MUTED2}">{T("Released per period, EGP · every closed period stays open for inspection","المصروف لكل فترة بالجنيه · كل فترة مغلقة تبقى متاحة للمراجعة")}</span></div>
          <div style="padding:14px 18px 18px">
            <div style="display:flex;align-items:center;gap:9px;margin-bottom:10px"><span style="flex:1"></span>{head}</div>
            {matrix}</div></div>""", unsafe_allow_html=True)


# ============================ EXECUTIVE ==================================== #
if "exec" in tab:
    with tab["exec"]:
        if not LIVE:
            v = P.VERDICTS[per_row["v"]]
            st.markdown(f"""<div style="max-width:880px" dir="{DIR}">{card(f'''
              <div style="display:flex;align-items:center;gap:14px;padding:18px 22px;background:#F6F8FB;border-bottom:1px solid {P.BORDER}">
                <div style="flex:1"><div style="font-size:10.5px;font-weight:600;letter-spacing:1.2px;color:{P.MUTED2};text-transform:uppercase;margin-bottom:4px">{T("Closed period summary","ملخص فترة مغلقة")}</div>
                  <div style="font-size:17px;font-weight:600;color:{P.NAVY}">{P.get_project(proj['id'])[('name' if EN else 'nameAr')]}</div>
                  <div style="font-size:12px;color:{P.MUTED2};margin-top:3px">{proj['code']} · {P.period_label(ss['per'], ss['lang'])}</div></div>
                {chip(per_row['v'], big=True)}</div>
              <div style="display:grid;grid-template-columns:repeat(4,1fr)">
                <div style="padding:18px 22px;border-inline-end:1px solid #EDF1F6"><div style="font-size:10.5px;font-weight:600;color:{P.MUTED2};text-transform:uppercase;margin-bottom:7px">{T("Released","المصروف")}</div><div class="mono" style="font-size:22px;font-weight:600;color:{P.NAVY}">{money(per_row['r'])}</div></div>
                <div style="padding:18px 22px;border-inline-end:1px solid #EDF1F6"><div style="font-size:10.5px;font-weight:600;color:{P.MUTED2};text-transform:uppercase;margin-bottom:7px">{T("Net savings","صافي الوفورات")}</div><div class="mono" style="font-size:22px;font-weight:600;color:{P.NAVY}">{money(per_row['s'])}</div></div>
                <div style="padding:18px 22px;border-inline-end:1px solid #EDF1F6"><div style="font-size:10.5px;font-weight:600;color:{P.MUTED2};text-transform:uppercase;margin-bottom:7px">{T("Cash","التحصيل")}</div><div class="mono" style="font-size:22px;font-weight:600;color:{P.NAVY}">{(str(per_row['c'])+'%') if per_row['c'] else '—'}</div></div>
                <div style="padding:18px 22px"><div style="font-size:10.5px;font-weight:600;color:{P.MUTED2};text-transform:uppercase;margin-bottom:7px">{T("Avg PPC","متوسط الإنجاز")}</div><div class="mono" style="font-size:22px;font-weight:600;color:{P.NAVY}">{(str(per_row['p'])+'%') if per_row['p'] else '—'}</div></div></div>
              <div style="padding:15px 22px;border-top:1px solid {P.BORDER};font-size:12px;color:{P.MUTED}">{T("Closed periods are read-only. The full cascade, distribution and audit trail live in the workbook exported at close.","الفترات المغلقة للقراءة فقط. السلسلة الكاملة والتوزيع وسجل التدقيق في الملف المُصدَّر عند الإغلاق.")}</div>''')}</div>""",
                        unsafe_allow_html=True)
        else:
            # Verdict banner
            st.markdown(f"""<div style="display:flex;align-items:center;gap:12px;background:{P.AMBER_FILL};border:1px solid #F6D6AD;border-radius:12px;padding:12px 16px;margin-bottom:14px" dir="{DIR}">
              <span style="width:9px;height:9px;border-radius:50%;background:{P.AMBER}"></span>
              <span style="font-size:13.5px;font-weight:600;color:{P.AMBER}">{T("PARTIAL PAYOUT","دفع جزئي")}</span>
              <span style="width:1px;height:16px;background:#F0C68F"></span>
              <span style="font-size:13px;color:#8A5A20;flex:1">{T(f"Cash gate at {pool['unlock_ratio']:.1%} · {money(pool['immediate_70_egp'])} EGP released, {money(pool['team_pool_raw_egp']-pool['unlocked_pool_egp'])} EGP locked",
                                                                    f"بوابة التحصيل {pool['unlock_ratio']:.1%} · صرف {money(pool['immediate_70_egp'])} وحجز {money(pool['team_pool_raw_egp']-pool['unlocked_pool_egp'])} جنيه")}</span></div>""",
                        unsafe_allow_html=True)
            # Hero cascade (layout A)
            held = pool["team_pool_raw_egp"] - pool["unlocked_pool_egp"]
            st.markdown(f"""<div style="display:flex;gap:14px;margin-bottom:14px" dir="{DIR}">
              <div style="flex:1;min-width:0;background:linear-gradient(135deg,{P.NAVY} 0%,{P.NAVY_DEEP} 100%);border-radius:16px;padding:24px 26px;position:relative;overflow:hidden">
                <div style="position:absolute;top:0;inset-inline-start:0;width:100%;height:3px;background:{P.AMBER}"></div>
                <div style="display:inline-flex;align-items:center;gap:8px;background:rgba(239,108,0,.16);border:1px solid rgba(239,108,0,.4);border-radius:999px;padding:5px 13px;margin-bottom:18px">
                  <span style="width:7px;height:7px;border-radius:50%;background:#FF8A2B"></span>
                  <span style="font-size:11px;font-weight:600;letter-spacing:1.5px;color:#FFB067;text-transform:uppercase">{T(f"Partial payout · gate {pool['unlock_ratio']:.1%}",f"دفع جزئي · بوابة {pool['unlock_ratio']:.1%}")}</span></div>
                <div style="font-size:11.5px;font-weight:600;letter-spacing:1.6px;color:#8CA3C2;text-transform:uppercase;margin-bottom:6px">{T("Released to the team now","المصروف للفريق الآن")}</div>
                <div style="display:flex;align-items:baseline;gap:12px"><span class="mono" style="font-size:60px;font-weight:600;color:#fff;letter-spacing:-2.4px">{money(pool['immediate_70_egp'])}</span><span style="font-size:20px;font-weight:500;color:{P.GOLD}">EGP</span></div>
                <div style="display:flex;margin-top:22px;border-top:1px solid #2A4467;padding-top:16px;gap:16px">
                  <div style="flex:1"><div style="font-size:10.5px;font-weight:600;color:#7B93B4;text-transform:uppercase;margin-bottom:5px">{T("Retained 30%","المحتجز ٣٠٪")}</div><div class="mono" style="font-size:20px;font-weight:600;color:#DCE5F0">{money(pool['retained_30_egp'])}</div></div>
                  <div style="width:1px;background:#2A4467"></div>
                  <div style="flex:1"><div style="font-size:10.5px;font-weight:600;color:#7B93B4;text-transform:uppercase;margin-bottom:5px">{T("Locked by gate","محجوز بالبوابة")}</div><div class="mono" style="font-size:20px;font-weight:600;color:#FFB067">{money(held)}</div></div>
                  <div style="width:1px;background:#2A4467"></div>
                  <div style="flex:1"><div style="font-size:10.5px;font-weight:600;color:#7B93B4;text-transform:uppercase;margin-bottom:5px">{T("Members paid","أعضاء مدفوعون")}</div><div class="mono" style="font-size:20px;font-weight:600;color:#DCE5F0">3 <span style="font-size:14px;color:#7B93B4">/ 4</span></div></div></div></div>
              <div style="width:430px;flex:none;background:#fff;border:1px solid {P.BORDER};border-radius:16px;padding:20px 22px">
                <div style="font-size:12.5px;font-weight:600;color:{P.NAVY}">{T("Savings to cash paid","من الوفورات إلى المدفوع")}</div>
                <div style="font-size:11px;color:{P.MUTED2};margin-bottom:16px">{T("Each step of the governance cascade","كل خطوة في سلسلة الحوكمة")}</div>
                {"".join(f'''<div style="margin-bottom:11px"><div style="display:flex;justify-content:space-between;margin-bottom:4px"><span style="font-size:11.5px;font-weight:600;color:{P.MUTED}">{lbl}</span><span class="mono" style="font-size:13px;font-weight:600;color:{col}">{money(val)}</span></div>
                  <div style="height:20px;width:{w}%;border-radius:5px;background:{col}"></div></div>'''
                  for lbl,val,col,w in [
                    (T("Net savings (S)","صافي الوفورات"), pool['net_savings_S_egp'], P.NAVY, 100),
                    (T("Team pool 35%","مجمع الفريق ٣٥٪"), pool['team_pool_raw_egp'], P.NAVY2, 35),
                    (T("Unlocked","المفتوح"), pool['unlocked_pool_egp'], P.GOLD2, 33.8),
                    (T("Immediate 70%","الدفع الفوري ٧٠٪"), pool['immediate_70_egp'], P.GOLD2, 23.6)])}
                <div style="display:flex;align-items:center;gap:9px;margin-top:10px;padding-top:12px;border-top:1px dashed {P.BORDER};font-size:11.5px;color:{P.MUTED}">
                  <span style="width:11px;height:11px;border-radius:3px;background:repeating-linear-gradient(135deg,#F3E4C0 0 3px,#FBF3DE 3px 6px)"></span>
                  {T(f"{money(held)} EGP locked until collection reaches 85%",f"{money(held)} جنيه محجوزة حتى يبلغ التحصيل ٨٥٪")}</div></div></div>""",
                        unsafe_allow_html=True)

            # 6 derivation tiles — st.metric (smoke test needs 'savings' + 'ppc')
            m = st.columns(6)
            adj = pool["adjusted_baseline_egp"]
            m[0].metric(T("Baseline cost", "التكلفة الأساسية"), f"{money(pool['baseline_egp'])}")
            m[1].metric(T("Adjusted baseline", "الأساس المعدّل"), f"{money(adj)}", "+8.0%", delta_color="off")
            m[2].metric(T("Actual cost", "التكلفة الفعلية"), f"{money(pool['actual_egp'])}", "−19.8%")
            m[3].metric(T("Net savings (S)", "صافي الوفورات"), f"{money(pool['net_savings_S_egp'])}")
            m[4].metric(T("Team pool 35%", "مجمع الفريق ٣٥٪"), f"{money(pool['team_pool_raw_egp'])}")
            m[5].metric(T("Avg site PPC", "متوسط الإنجاز"), f"{(site_agg['avg_ppc'] or 0):.0%}",
                        T("1 LTI open", "إصابة قائمة"), delta_color="inverse")

            # Insights grouped Money / Team / Risk
            def ins(group, gcol, items):
                body = "".join(
                    f'''<div style="padding:13px 16px;border-top:1px solid #EDF1F6"><div style="font-size:14px;font-weight:600;color:{P.NAVY};margin-bottom:3px">{h}</div>
                    <div style="font-size:12.5px;color:{P.MUTED};line-height:1.5">{b}</div>
                    {f'<div style="display:inline-flex;align-items:center;gap:7px;margin-top:8px;padding:5px 10px;background:#FBF3DE;border-radius:7px;font-size:11px;font-weight:600;color:#8A6A15">→ {act}</div>' if act else ''}</div>'''
                    for h, b, act in items)
                return f'''<div style="display:flex;align-items:center;gap:8px;padding:9px 16px;background:#F6F8FB;border-top:1px solid {P.BORDER};border-bottom:1px solid {P.BORDER}">
                  <span style="width:5px;height:5px;border-radius:50%;background:{gcol}"></span>
                  <span style="font-size:10.5px;font-weight:600;letter-spacing:1.2px;color:{P.MUTED};text-transform:uppercase">{group}</span></div>{body}'''

            insights_html = ins(T("Money", "المال"), P.GREEN, [
                (T("Delivered 19.8% under the inflation-adjusted baseline", "أقل بنسبة ١٩٫٨٪ من الأساس المعدّل"),
                 T(f"{money(pool['net_savings_S_egp'])} EGP net savings after the 0.95 quality factor and 150,000 EGP bad debt.",
                   f"صافي وفورات {money(pool['net_savings_S_egp'])} جنيه بعد معامل الجودة ٠٫٩٥ وديون ١٥٠٬٠٠٠."), None),
                (T(f"{money(held)} EGP stays locked until collection hits 85%", f"{money(held)} جنيه محجوزة حتى ٨٥٪"),
                 T("Cash at 82% unlocks 96.5% of the pool pro-rata. 3 more points releases the balance.",
                   "التحصيل ٨٢٪ يفتح ٩٦٫٥٪ تناسبياً. ٣ نقاط إضافية تُفرج عن الرصيد."),
                 T("Chase the two open invoices · Commercial · by 31 Aug", "تابع الفاتورتين · التجاري · قبل ٣١ أغسطس"))])
            insights_html += ins(T("Team", "الفريق"), P.NAVY2, [
                (T("2 of 4 members clear every gate", "٢ من ٤ يجتازون كل البوابات"),
                 T("Mona Adel loses 50% on the L&D SLA. Khaled Samir is out at 70% PPC vs the 85% gate.",
                   "منى تفقد ٥٠٪ لاتفاقية التدريب. خالد مستبعد بإنجاز ٧٠٪ مقابل ٨٥٪."), None),
                (T("Ahmed Fathy takes 70% of the pool — 543,495 EGP", "أحمد فتحي يأخذ ٧٠٪ — ٥٤٣٬٤٩٥ جنيه"),
                 T("L3 badge (×1.35), full weight, 92% PPC and 200,000 EGP of VE. A key-person risk worth naming.",
                   "شهادة L3 ووزن كامل وإنجاز ٩٢٪ وهندسة قيمة. مخاطرة اعتماد على شخص واحد."), None)])
            insights_html += ins(T("Risk", "المخاطر"), P.BRICK, [
                (T("Supplier quote is 44,500 EGP over target", "عرض المورد أعلى بـ٤٤٬٥٠٠ جنيه"),
                 T("Copper cable is the worst line at +16.1%. Rebar and earthworks absorbed part of it.",
                   "كابل النحاس أسوأ بند بزيادة ١٦٫١٪. الحديد والحفر امتصّا جزءاً."),
                 T("Re-tender the cable line · Procurement · by 10 Aug", "أعد طرح الكابل · المشتريات · قبل ١٠ أغسطس")),
                (T(f"Rate coverage {P.rate_coverage(audited):.0%} — the 850k crane line is unaudited", f"تغطية الأسعار {P.rate_coverage(audited):.0%} — الرافعة غير مدققة"),
                 T("4 lines exceed the 10,000 EGP scope guardrail without a VO; unsigned scope carries a 50% penalty.",
                   "٤ بنود تتجاوز حد ١٠٬٠٠٠ بدون أمر تغيير؛ النطاق غير الموقّع خصمه ٥٠٪."), None)])

            # payout by member bars
            paid = dist.sort_values("gross_share_egp", ascending=False)
            maxg = paid["gross_share_egp"].max() or 1
            bars = ""
            for _, r in paid.iterrows():
                col = P.GREEN if r["status"] == "APPROVED_FULL" else P.AMBER if r["status"] == "PENALTY_APPLIED" else P.BRICK
                w = (r["gross_share_egp"] / maxg) * 100
                bars += f"""<div style="margin-bottom:11px"><div style="display:flex;justify-content:space-between;margin-bottom:5px"><span style="font-size:12.5px;font-weight:600;color:{'#8494AA' if r['gross_share_egp']==0 else P.NAVY}">{r['name']}</span><span class="mono" style="font-size:12.5px;font-weight:600;color:{P.BRICK if r['gross_share_egp']==0 else P.NAVY}">{money(r['gross_share_egp'])}</span></div>
                  <div style="height:12px;border-radius:3px;background:#EDF1F6"><div style="height:12px;width:{w}%;border-radius:3px;background:{col}"></div></div></div>"""

            st.markdown(f"""<div style="display:flex;gap:14px;margin-top:6px" dir="{DIR}">
              <div style="flex:1;min-width:0">
                <div style="display:flex;align-items:baseline;gap:10px;margin-bottom:12px"><h2 style="margin:0;font-size:15px;font-weight:600;color:{P.NAVY}">{T("What the numbers say","ما تقوله الأرقام")}</h2><span style="font-size:11.5px;color:{P.MUTED2}">{T("auto-generated · 6 findings","مولّدة تلقائياً · ٦ نتائج")}</span></div>
                <div style="background:#fff;border:1px solid {P.BORDER};border-radius:14px;overflow:hidden">{insights_html}</div></div>
              <div style="width:430px;flex:none">
                <div style="background:#fff;border:1px solid {P.BORDER};border-radius:14px;padding:18px 20px">
                  <div style="font-size:12.5px;font-weight:600;color:{P.NAVY}">{T("Payout by member","التوزيع على الأعضاء")}</div>
                  <div style="font-size:11px;color:{P.MUTED2};margin-bottom:16px">{T("Gross share, EGP · colour = status","الحصة الإجمالية · اللون = الحالة")}</div>{bars}</div></div></div>""",
                        unsafe_allow_html=True)


# ============================ TEAM PAYOUT ================================== #
if "team" in tab:
    with tab["team"]:
        cap_on = st.toggle(T("Model a 40% concentration cap", "محاكاة سقف تركّز ٤٠٪"), value=ss["cap"], key="captoggle")
        if cap_on != ss["cap"]:
            ss["cap"] = cap_on; st.rerun()

        d = dist.copy()
        note = T("Ahmed Fathy takes 70.3% of the pool. The toggle models a 40% cap and redistributes the excess pro-rata to the other eligible members — it models, it does not enforce.",
                 "أحمد فتحي يأخذ ٧٠٫٣٪ من المجمع. المفتاح يحاكي سقف ٤٠٪ ويعيد توزيع الفائض تناسبياً — محاكاة فقط لا تطبيق.")
        eligible = d[d["gross_share_egp"] > 0].copy()
        total_gross = eligible["gross_share_egp"].sum()
        if cap_on and total_gross > 0:
            cap_amt = total_gross * 0.40
            capped = eligible["gross_share_egp"].clip(upper=cap_amt)
            excess = eligible["gross_share_egp"].sum() - capped.sum()
            room = (cap_amt - capped)
            room_sum = room[room > 0].sum()
            add = room.clip(lower=0) / room_sum * excess if room_sum else 0
            eligible["capped"] = capped + add
        else:
            eligible["capped"] = eligible["gross_share_egp"]
        maxc = eligible["capped"].max() or 1

        conc = ""
        for _, r in eligible.sort_values("capped", ascending=False).iterrows():
            pct = r["capped"] / total_gross * 100 if total_gross else 0
            w = r["capped"] / maxc * 100
            pcol = P.BRICK if pct > 45 else P.MUTED
            conc += f"""<div style="display:flex;align-items:center;gap:14px;margin-bottom:10px">
              <span style="width:118px;flex:none;font-size:12.5px;font-weight:600;color:{P.NAVY}">{r['name']}</span>
              <span style="flex:1;height:14px;border-radius:3px;background:#EDF1F6"><span style="display:block;height:14px;width:{w}%;border-radius:3px;background:{P.NAVY if pct<=45 else P.BRICK}"></span></span>
              <span class="mono" style="width:54px;text-align:end;font-weight:600;color:{pcol}">{pct:.1f}%</span>
              <span class="mono" style="width:82px;text-align:end;font-weight:600;color:{P.NAVY}">{money(r['capped'])}</span></div>"""

        # pool tiles
        forfeited = 102051
        tiles = st.columns(4)
        tiles[0].metric(T("Base pool 80%", "المجمع الأساسي ٨٠٪"), money(pool["base_pool_80_egp"]))
        tiles[1].metric(T("Performance pool 20%", "مجمع الأداء ٢٠٪"), money(pool["performance_pool_20_egp"]))
        tiles[2].metric(T("Paid now 70%", "مدفوع الآن ٧٠٪"), money(pool["immediate_70_egp"]))
        tiles[3].metric(T("Forfeited to penalties", "مفقود بالخصومات"), money(forfeited))

        st.markdown(f"""<div style="background:#fff;border:1px solid {P.BORDER};border-inline-start:4px solid {P.BRICK};border-radius:14px;padding:18px 20px;margin:14px 0" dir="{DIR}">
          <h2 style="margin:0 0 4px;font-size:14.5px;font-weight:600;color:{P.NAVY}">{T("Concentration risk","مخاطر التركّز")}</h2>
          <p style="margin:0 0 16px;font-size:12.5px;color:{P.MUTED}">{note}</p>{conc}
          <div style="margin-top:12px;padding-top:12px;border-top:1px dashed {P.BORDER};font-size:11.5px;color:#8A6A15"><b>{T("Governance decision","قرار حوكمة")}</b> — {T("a cap is not in the scheme today.","السقف غير موجود في النظام حالياً.")}</div></div>""",
                    unsafe_allow_html=True)

        # distribution table
        heads = [T("Member","العضو"), "L&D", "PPC", T("Base","أساسي"), T("Perf.","أداء"),
                 T("Gross","الإجمالي"), T("Now 70%","فوري"), T("Held 30%","محتجز"), T("Status","الحالة")]
        th = "".join(f'<th style="text-align:{"start" if i in (0,1,8) else "end"};padding:9px 12px;font-size:10.5px;font-weight:600;letter-spacing:.9px;color:{P.MUTED};text-transform:uppercase;border-bottom:1px solid {P.BORDER}">{h}</th>' for i, h in enumerate(heads))
        trs = ""
        stat_map = {"APPROVED_FULL": (P.GREEN, P.GREEN_FILL, T("Approved","معتمد")),
                    "PENALTY_APPLIED": (P.AMBER, P.AMBER_FILL, T("Penalty","خصم")),
                    "INELIGIBLE_SLA_PPC": (P.BRICK, P.BRICK_FILL, T("Ineligible","غير مؤهل")),
                    "DISQUALIFIED_SAFETY": (P.BRICK, P.BRICK_FILL, T("Disqualified","مستبعد"))}
        for _, r in dist.iterrows():
            sc, sf, sl = stat_map.get(r["status"], (P.MUTED, "#EDF1F6", r["status"]))
            trs += f"""<tr style="border-bottom:1px solid #EDF1F6">
              <td style="padding:12px"><div style="font-size:13px;font-weight:600">{r['name']}</div><div style="font-size:11px;color:{P.MUTED2}">{r['role']}</div></td>
              <td style="padding:12px"><span style="font-size:11px;font-weight:600;color:#8A6A15;background:#FBF3DE;border-radius:5px;padding:3px 7px">{r['ld_badge'].replace('Level ','L')} ×{r['badge_multiplier']}</span></td>
              <td class="mono" style="padding:12px;text-align:end;color:{P.GREEN if r['ppc']>=0.85 else P.BRICK}">{r['ppc']:.0%}</td>
              <td class="mono" style="padding:12px;text-align:end">{money(r['base_share_egp'])}</td>
              <td class="mono" style="padding:12px;text-align:end">{money(r['perf_share_egp'])}</td>
              <td class="mono" style="padding:12px;text-align:end;font-weight:600;color:{P.NAVY}">{money(r['gross_share_egp'])}</td>
              <td class="mono" style="padding:12px;text-align:end;color:{P.GOLD2}">{money(r['immediate_70_egp'])}</td>
              <td class="mono" style="padding:12px;text-align:end;color:{P.MUTED}">{money(r['retained_30_egp'])}</td>
              <td style="padding:12px"><span style="font-size:11px;font-weight:600;color:{sc};background:{sf};border-radius:5px;padding:3px 8px">{sl}</span></td></tr>"""
        st.markdown(f"""<div style="background:#fff;border:1px solid {P.BORDER};border-radius:14px;overflow:hidden" dir="{DIR}">
          <div style="padding:14px 18px;border-bottom:1px solid {P.BORDER};display:flex;justify-content:space-between">
            <h2 style="margin:0;font-size:14.5px;font-weight:600;color:{P.NAVY}">{T("Distribution detail","تفصيل التوزيع")}</h2>
            <span style="font-size:11.5px;color:{P.MUTED2}">{T(f"4 members · unlocked pool {money(pool['unlocked_pool_egp'])} EGP",f"٤ أعضاء · المجمع {money(pool['unlocked_pool_egp'])} جنيه")}</span></div>
          <table style="width:100%;border-collapse:collapse"><thead><tr style="background:#F6F8FB">{th}</tr></thead><tbody>{trs}</tbody></table></div>""",
                    unsafe_allow_html=True)


# ============================ BOQ AUDIT ==================================== #
if "boq" in tab:
    with tab["boq"]:
        tot_ppv = sum(a.ppv_total_egp or 0 for a in audited)
        cov = P.rate_coverage(audited)
        cc = st.columns(4)
        cc[0].metric(T("Total PPV", "إجمالي الانحراف"), f"{money(tot_ppv)} EGP")
        cc[1].metric(T("Overspend lines", "بنود التجاوز"), sum(1 for a in audited if (a.ppv_total_egp or 0) > 0))
        cc[2].metric(T("Unapproved scope", "نطاق غير معتمد"), sum(1 for a in audited if a.unapproved_scope_flag))
        cc[3].metric(T("Rate coverage", "تغطية الأسعار"), f"{cov:.0%}",
                     T("gap to close", "فجوة") if cov < 0.95 else "", delta_color="inverse")
        rows = ""
        for a in audited:
            fl = ", ".join(a.flags)
            over = (a.ppv_total_egp or 0) > 0
            rows += f"""<tr style="border-bottom:1px solid #EDF1F6"><td style="padding:11px 14px"><div style="font-size:12.5px;font-weight:600" class="mono">{a.item_code}</div><div style="font-size:11px;color:{P.MUTED2}">{a.description}</div></td>
              <td class="mono" style="padding:11px 14px;text-align:end">{money(a.quoted_rate_egp)}</td>
              <td class="mono" style="padding:11px 14px;text-align:end;color:{P.MUTED}">{money(a.target_rate_egp) if a.target_rate_egp else '—'}</td>
              <td class="mono" style="padding:11px 14px;text-align:end;font-weight:600;color:{P.BRICK if over else P.GREEN if a.ppv_total_egp else P.MUTED2}">{money(a.ppv_total_egp) if a.ppv_total_egp is not None else '—'}</td>
              <td style="padding:11px 14px;font-size:11px;color:{P.MUTED}">{fl}</td></tr>"""
        st.markdown(f"""<div style="background:#fff;border:1px solid {P.BORDER};border-radius:14px;overflow:hidden;margin-top:14px" dir="{DIR}">
          <table style="width:100%;border-collapse:collapse"><thead><tr style="background:#F6F8FB">
          {"".join(f'<th style="text-align:{"start" if i in (0,4) else "end"};padding:9px 14px;font-size:10.5px;font-weight:600;color:{P.MUTED};text-transform:uppercase;border-bottom:1px solid {P.BORDER}">{h}</th>' for i,h in enumerate([T("Item","البند"),T("Quoted","العرض"),T("Target","المستهدف"),"PPV",T("Flags","الأعلام")]))}
          </tr></thead><tbody>{rows}</tbody></table></div>""", unsafe_allow_html=True)


# ============================ SITE KPIs ==================================== #
if "site" in tab:
    with tab["site"]:
        def track(label, val, gate, zones):
            col = P.GREEN if val >= gate else P.AMBER
            return f"""<div style="background:#fff;border:1px solid {P.BORDER};border-radius:12px;padding:16px 18px">
              <div style="display:flex;justify-content:space-between;margin-bottom:8px"><span style="font-size:12.5px;font-weight:600;color:{P.NAVY}">{label}</span><span class="mono" style="font-weight:600;color:{col}">{val:.0%}</span></div>
              <div style="position:relative;height:10px;border-radius:5px;background:{zones}"><div style="position:absolute;inset-inline-start:{gate*100}%;top:-3px;width:2px;height:16px;background:{P.GOLD}"></div><div style="position:absolute;inset-inline-start:0;top:0;height:10px;width:{val*100}%;border-radius:5px;background:{P.NAVY}"></div></div>
              <div style="margin-top:5px;font-size:10.5px;color:{P.MUTED2}">{T('gate','بوابة')} {gate:.0%}</div></div>"""
        ppc = site_agg.get("avg_ppc") or 0
        oee = site_agg.get("avg_oee") or 0
        st.markdown(f"""<div style="display:flex;gap:12px;margin-bottom:12px" dir="{DIR}">
          <div style="flex:1">{track(T('Avg PPC','متوسط الإنجاز'),ppc,0.85,'linear-gradient(90deg,#FFF3E0 0 85%,#E8F5E9 85% 100%)')}</div>
          <div style="flex:1">{track(T('Avg OEE','كفاءة المعدات'),oee,0.95,'linear-gradient(90deg,#FFF3E0 0 95%,#E8F5E9 95% 100%)')}</div></div>""", unsafe_allow_html=True)
        sc = st.columns(4)
        sc[0].metric(T("Total NCRs", "عدم المطابقة"), site_agg["total_ncr"])
        sc[1].metric(T("Total LTIs", "الإصابات"), site_agg["total_lti"])
        sc[2].metric(T("Sites reported", "المواقع"), len(RES["site"]["logs"]))
        sc[3].metric(T("Avg PPC", "متوسط الإنجاز"), f"{ppc:.0%}")
        if lti_unreconciled:
            st.markdown(f"""<div style="background:{P.BRICK_FILL};border:1px solid #EDC7C3;border-radius:10px;padding:12px 15px;margin-top:12px;font-size:13px;color:{P.BRICK}" dir="{DIR}">
              {T("⚠ The site log reports 1 LTI but the payout was computed with the safety gate at 0 — reconcile before payroll.","⚠ يُسجّل الموقع إصابة واحدة بينما حُسب التوزيع وبوابة السلامة على صفر — راجع قبل الرواتب.")}</div>""", unsafe_allow_html=True)
        with st.expander(T("CEO daily digest", "الملخص اليومي")):
            st.markdown(RES["site"]["digest_md"])


# ============================ DOWNLOADS ==================================== #
if "dl" in tab:
    with tab["dl"]:
        st.markdown(f'<div style="font-size:15px;font-weight:600;color:{P.NAVY};margin-bottom:12px" dir="{DIR}">{T("Export · board pack &amp; source reports","تصدير · حزمة المجلس والتقارير")}</div>', unsafe_allow_html=True)
        dc = st.columns(2)
        with dc[0]:
            st.download_button("⬇  UNITED_BROTHERS_ELEVATE_MASTER.xlsx", data=RES["xlsx"],
                               file_name="UNITED_BROTHERS_ELEVATE_MASTER.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", width="stretch")
            st.download_button("⬇  boq_audit_report.md", data=RES["boq"]["report_md"],
                               file_name="boq_audit_report.md", width="stretch")
        with dc[1]:
            st.download_button("⬇  site_daily_digest.md", data=RES["site"]["digest_md"],
                               file_name="site_daily_digest.md", width="stretch")
            st.download_button("⬇  gainsharing_result.md", data=gs.summary(),
                               file_name="gainsharing_result.md", width="stretch")

st.markdown("</div>", unsafe_allow_html=True)
