# -*- coding: utf-8 -*-
"""Tests for the adaptive gainsharing engine — governance rules.
اختبارات محرك المشاركة في المكاسب."""
import math

import pytest

from conftest import RATES
from gainsharing_calculator import (
    GainsharingCalculator, ProjectFinancials, TeamMember,
)


def _calc():
    return GainsharingCalculator(rates_path=RATES)


def _fin(**kw):
    base = dict(
        project_name="T", baseline_cost_egp=10_000_000.0, actual_cost_egp=9_000_000.0,
        cash_collected_pct=0.90, quality_factor=1.0, escalation_commodity="default",
        escalation_delta_override=0.0, bad_debt_egp=0.0,
        subcontractor_value_egp=0.0, lost_time_injuries=0,
    )
    base.update(kw)
    return ProjectFinancials(**base)


# --------------------------------------------------------------------------- #
#  Savings & escalation
# --------------------------------------------------------------------------- #
def test_savings_basic():
    s = _calc().compute_savings(_fin())
    # No escalation, no bad debt, QF=1 -> S = 10M - 9M = 1M
    assert s["net_savings_S"] == pytest.approx(1_000_000.0)


def test_escalation_raises_baseline():
    s = _calc().compute_savings(_fin(escalation_delta_override=0.10))
    # adjusted baseline = 10M * 1.1 = 11M ; S = 11M - 9M = 2M
    assert s["adjusted_baseline"] == pytest.approx(11_000_000.0)
    assert s["net_savings_S"] == pytest.approx(2_000_000.0)


def test_quality_factor_scales_savings():
    s = _calc().compute_savings(_fin(quality_factor=0.5))
    assert s["net_savings_S"] == pytest.approx(500_000.0)


def test_bad_debt_isolated_from_savings():
    s = _calc().compute_savings(_fin(bad_debt_egp=200_000.0))
    # S = (10M - 9M - 0.2M) * 1 = 0.8M
    assert s["net_savings_S"] == pytest.approx(800_000.0)


def test_negative_savings_floored_at_zero():
    s = _calc().compute_savings(_fin(actual_cost_egp=11_000_000.0))
    assert s["net_savings_S"] == 0.0


# --------------------------------------------------------------------------- #
#  Cash gate tiers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("collected,expected_status,expected_ratio", [
    (0.90, "FULL_UNLOCK", 1.0),
    (0.85, "FULL_UNLOCK", 1.0),
    (0.80, "PARTIAL_UNLOCK", 0.80 / 0.85),
    (0.75, "PARTIAL_UNLOCK", 0.75 / 0.85),
    (0.74, "HOLDBACK", 0.0),
    (0.10, "HOLDBACK", 0.0),
])
def test_cash_gate_tiers(collected, expected_status, expected_ratio):
    calc = _calc()
    pool = calc.compute_pool(1_000_000.0, _fin(cash_collected_pct=collected))
    assert pool["gate_status"] == expected_status
    assert pool["unlock_ratio"] == pytest.approx(expected_ratio, abs=1e-4)


def test_team_pool_is_35_percent():
    pool = _calc().compute_pool(1_000_000.0, _fin(cash_collected_pct=0.90))
    assert pool["raw_pool"] == pytest.approx(350_000.0)


def test_80_20_and_70_30_splits():
    pool = _calc().compute_pool(1_000_000.0, _fin(cash_collected_pct=0.90))
    unlocked = pool["unlocked_pool"]
    assert pool["base_pool"] == pytest.approx(unlocked * 0.80)
    assert pool["performance_pool"] == pytest.approx(unlocked * 0.20)
    assert pool["immediate_payout"] == pytest.approx(unlocked * 0.70)
    assert pool["retained_cushion"] == pytest.approx(unlocked * 0.30)


def test_subcontractor_reserve_10_percent():
    pool = _calc().compute_pool(1_000_000.0, _fin(subcontractor_value_egp=2_000_000.0))
    assert pool["subcontractor_reserve"] == pytest.approx(200_000.0)


# --------------------------------------------------------------------------- #
#  Distribution, gates & multipliers
# --------------------------------------------------------------------------- #
def test_safety_gate_disqualifies_team():
    calc = _calc()
    fin = _fin(lost_time_injuries=1)
    members = [TeamMember("A", ppc=0.95, ld_badge="Level 3")]
    result = calc.run(fin, members)
    assert result.safety_disqualified is True
    row = result.distribution_df.iloc[0]
    assert row["gross_share_egp"] == 0.0
    assert row["status"] == "DISQUALIFIED_SAFETY"


def test_ppc_below_gate_is_ineligible():
    calc = _calc()
    members = [
        TeamMember("Eligible", ppc=0.90, ld_badge="Level 1"),
        TeamMember("LowPPC", ppc=0.70, ld_badge="Level 1"),
    ]
    df = calc.run(_fin(), members).distribution_df.set_index("name")
    assert df.loc["LowPPC", "base_share_egp"] == 0.0
    assert df.loc["LowPPC", "status"] == "INELIGIBLE_SLA_PPC"
    assert df.loc["Eligible", "base_share_egp"] > 0.0


def test_ld_badge_multiplier_weights_shares():
    calc = _calc()
    # Two identical members except badge; L3 should get 1.35x the weight of L1.
    members = [
        TeamMember("L1", ppc=0.95, ld_badge="Level 1", time_weight=1.0),
        TeamMember("L3", ppc=0.95, ld_badge="Level 3", time_weight=1.0),
    ]
    df = calc.run(_fin(), members).distribution_df.set_index("name")
    ratio = df.loc["L3", "base_share_egp"] / df.loc["L1", "base_share_egp"]
    assert ratio == pytest.approx(1.35, rel=1e-3)


def test_ld_failure_forfeits_half_into_perf_pool():
    calc = _calc()
    # One member fails L&D -> 50% of their base share forfeited to perf pool.
    members = [
        TeamMember("Fail", ppc=0.95, ld_badge="Level 1", ld_sla_met=False),
    ]
    df = calc.run(_fin(cash_collected_pct=0.90), members).distribution_df.set_index("name")
    # With a single member, base_pool would fully be theirs; 50% forfeited then
    # returns via the 20% perf pool (no perf points -> not redistributed to them).
    assert df.loc["Fail", "status"] == "PENALTY_APPLIED"
    # Base share is exactly half of what an unpenalised member would get.
    clean = calc.run(_fin(cash_collected_pct=0.90),
                     [TeamMember("Clean", ppc=0.95, ld_badge="Level 1")])
    clean_base = clean.distribution_df.iloc[0]["base_share_egp"]
    assert df.loc["Fail", "base_share_egp"] == pytest.approx(clean_base * 0.5, rel=1e-6)


def test_vested_resignation_note():
    calc = _calc()
    members = [TeamMember("R", ppc=0.95, resigning_clean_handover=True)]
    df = calc.run(_fin(), members).distribution_df.set_index("name")
    assert "VESTED_30PCT_CLEAN_HANDOVER" in df.loc["R", "notes"]


def test_distribution_columns_present_for_excel():
    calc = _calc()
    df = calc.run(_fin(), [TeamMember("A", ppc=0.95)]).distribution_df
    for col in ("section_sla_met", "ld_sla_met", "unapproved_scope_breach"):
        assert col in df.columns


def test_result_dataframes_nonempty():
    calc = _calc()
    result = calc.run(_fin(), [TeamMember("A", ppc=0.95)])
    assert not result.pool_df.empty
    assert not result.distribution_df.empty
    assert not result.audit_df.empty
