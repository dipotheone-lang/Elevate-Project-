# -*- coding: utf-8 -*-
"""Tests for the persistence backend (portfolio_store) and the engine's
safety-reconciliation check. اختبارات الواجهة الخلفية."""
import pytest

from conftest import RATES
import portfolio_store as store
import portfolio_data as P
from gainsharing_calculator import (
    GainsharingCalculator, ProjectFinancials, TeamMember,
    safety_unreconciled, reconcile_safety,
)


@pytest.fixture
def st_store(tmp_path):
    """Isolated store on a temp SQLite file; restores the default path after."""
    orig = store.DB_PATH
    store.reset(tmp_path / "t.db")
    yield store
    store.reset(orig)


def _gs(cash=0.82, lti=0):
    fin = ProjectFinancials("T", 12_000_000, 10_400_000, cash_collected_pct=cash,
                            quality_factor=0.95, escalation_commodity="steel_rebar",
                            bad_debt_egp=150_000, subcontractor_value_egp=3_000_000,
                            lost_time_injuries=lti)
    members = [TeamMember("Ahmed", "SM", ld_badge="Level 3", ppc=0.92),
               TeamMember("Khaled", "Foreman", ld_badge="Level 1", ppc=0.70)]
    return GainsharingCalculator(RATES).run(fin, members)


# --------------------------------------------------------------------------- #
#  Seed & read
# --------------------------------------------------------------------------- #
def test_store_seeds_four_projects(st_store):
    ps = st_store.projects()
    assert len(ps) == 4
    assert {p["id"] for p in ps} == {"p1", "p2", "p3", "p4"}


def test_seeded_period_matches_authored(st_store):
    row = st_store.period_row("p1", "jul")
    assert row["v"] == "PARTIAL"
    assert row["r"] == 541130
    assert row["c"] == 82 and row["p"] == 84


def test_portfolio_totals_match_authored(st_store):
    tot = st_store.portfolio_totals("jul")
    # Ain Sokhna 541,130 + New Capital 769,300 released this period.
    assert tot["released"] == 541130 + 769300
    assert tot["paying"] == 2
    # blocked = Greater Cairo 705,250 + Suez 493,500 + Ain Sokhna 28,282
    assert tot["blocked"] == 705250 + 493500 + 28282
    assert len(tot["blocked_rows"]) == 3
    assert tot["blocked_rows"][0]["cause"] == "safety"  # largest, safety first


def test_suez_decays_to_holdback(st_store):
    suez = st_store.project("p3")
    verdicts = [x["v"] for x in suez["periods"]]
    assert verdicts == ["PARTIAL", "HOLD", "HOLD", "HOLD", "OPEN"]


# --------------------------------------------------------------------------- #
#  Governance helpers
# --------------------------------------------------------------------------- #
def test_blocking_cause_precedence():
    assert P.blocking_cause("PARTIAL_UNLOCK", True) == "safety"   # safety first
    assert P.blocking_cause("HOLDBACK", False) == "cash"
    assert P.blocking_cause("PARTIAL_UNLOCK", False) == "gate"
    assert P.blocking_cause("FULL_UNLOCK", False) is None


def test_unlock_forecast_gate():
    f = P.unlock_forecast("gate", 28282, 0.82)
    assert f["recoverable"] == 28282
    assert f["points_needed"] == pytest.approx(3.0)


# --------------------------------------------------------------------------- #
#  Safety reconciliation (engine, PORT_GUIDE §7)
# --------------------------------------------------------------------------- #
def test_safety_unreconciled():
    assert safety_unreconciled(0, 1) is True
    assert safety_unreconciled(1, 1) is False
    assert safety_unreconciled(2, 1) is False


def test_reconcile_safety_returns_warning():
    fin = ProjectFinancials("T", 1, 1, cash_collected_pct=0.9, lost_time_injuries=0)
    assert reconcile_safety(fin, {"total_lti": 1})["code"] == "SAFETY_UNRECONCILED"
    assert reconcile_safety(fin, {"total_lti": 0}) is None


# --------------------------------------------------------------------------- #
#  Close period → persist + queue escalation
# --------------------------------------------------------------------------- #
def test_close_period_persists_and_queues(st_store):
    gs = _gs(cash=0.82)  # partial unlock -> gate cause
    row = st_store.close_period("p1", "jul", gs_result=gs,
                                site_agg={"total_lti": 1, "total_ncr": 1, "avg_ppc": 0.84, "avg_oee": 0.95})
    assert row["v"] == "PARTIAL"
    q = st_store.escalation_queue("jul")
    assert len(q) == 1
    assert q[0]["cause"] == "gate" and q[0]["owner"] == "Commercial"
    assert q[0]["status"] == "queued"
    st_store.mark_escalation_sent(q[0]["id"])
    assert st_store.escalation_queue("jul")[0]["status"] == "sent"


def test_close_holdback_blocks_full_pool(st_store):
    gs = _gs(cash=0.60)  # < 75% -> holdback
    row = st_store.close_period("p3", "jul", gs_result=gs,
                                site_agg={"total_lti": 0, "total_ncr": 0, "avg_ppc": 0.84})
    assert row["v"] == "HOLD"
    assert st_store.escalation_queue("jul")[0]["cause"] == "cash"
