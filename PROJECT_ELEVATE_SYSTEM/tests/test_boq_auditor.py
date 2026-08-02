# -*- coding: utf-8 -*-
"""Tests for the BOQ & quote auditor. اختبارات مدقق جداول الكميات."""
from conftest import RATES
from boq_auditor import BOQAuditor, QuoteLine


def _auditor():
    return BOQAuditor(rates_path=RATES)


def test_regex_parse_pipe_format():
    raw = "CIV-CONC-C30 | Concrete | m3 | 100 | 2600 | no"
    lines = _auditor()._parse_with_regex(raw)
    assert len(lines) == 1
    assert lines[0].item_code == "CIV-CONC-C30"
    assert lines[0].quantity == 100.0
    assert lines[0].unit_rate_egp == 2600.0
    assert lines[0].approved_vo is False


def test_regex_skips_malformed_lines():
    raw = "not a valid line\nCIV-CONC-C30 | Concrete | m3 | 100 | 2600 | yes"
    lines = _auditor()._parse_with_regex(raw)
    assert len(lines) == 1
    assert lines[0].approved_vo is True


def test_ppv_overspend_positive():
    # Quoted above target -> positive PPV (overspend).
    q = [QuoteLine("CIV-CONC-C30", "Concrete", "m3", 100, 2600)]  # target 2450
    a = _auditor().audit(q)[0]
    assert a.ppv_per_unit_egp == 150.0
    assert a.ppv_total_egp == 15_000.0
    assert "OVERSPEND" in a.flags


def test_ppv_under_target_negative():
    q = [QuoteLine("CIV-STEEL-REBAR", "Steel", "ton", 10, 47000)]  # target 48500
    a = _auditor().audit(q)[0]
    assert a.ppv_per_unit_egp == -1500.0
    assert "UNDER_TARGET" in a.flags


def test_unapproved_scope_flag_over_threshold():
    # Line total 100*2600 = 260,000 > 10,000 EGP and no approved VO.
    q = [QuoteLine("CIV-CONC-C30", "Concrete", "m3", 100, 2600, approved_vo=False)]
    a = _auditor().audit(q)[0]
    assert a.unapproved_scope_flag is True
    assert "UNAPPROVED_SCOPE" in a.flags


def test_approved_vo_clears_scope_flag():
    q = [QuoteLine("CIV-CONC-C30", "Concrete", "m3", 100, 2600, approved_vo=True)]
    a = _auditor().audit(q)[0]
    assert a.unapproved_scope_flag is False
    assert "UNAPPROVED_SCOPE" not in a.flags


def test_small_line_not_flagged():
    # 1 * 2600 = 2600 EGP < 10,000 threshold.
    q = [QuoteLine("CIV-CONC-C30", "Concrete", "m3", 1, 2600, approved_vo=False)]
    a = _auditor().audit(q)[0]
    assert a.unapproved_scope_flag is False


def test_unknown_item_has_no_target():
    q = [QuoteLine("MYSTERY-ITEM", "Unknown", "ls", 1, 5000)]
    a = _auditor().audit(q)[0]
    assert a.target_rate_egp is None
    assert "NO_TARGET_RATE" in a.flags


def test_ve_candidate_flagged():
    q = [QuoteLine("CIV-CONC-C30", "Concrete", "m3", 1, 2600)]  # ve_potential=true
    a = _auditor().audit(q)[0]
    assert a.ve_potential is True
    assert "VE_CANDIDATE" in a.flags


def test_report_markdown_contains_brand_and_totals():
    raw = "CIV-CONC-C30 | Concrete | m3 | 100 | 2600 | no"
    res = _auditor().run(raw, supplier="ACME", project="P1")
    md = res["report_md"]
    assert "United Brothers Co." in md
    assert "ACME" in md
    assert "Purchase Price Variance" in md
