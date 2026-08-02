# -*- coding: utf-8 -*-
"""Tests for the daily site tracker & PPC engine.
اختبارات محرك تتبع الموقع اليومي."""
import pytest

from conftest import RATES
from site_tracker import SiteTracker


def _tracker():
    return SiteTracker(rates_path=RATES)


def test_parse_english_metrics():
    note = "PPC today 88%. NCR: 2 minor. Crane uptime 96%. LTI 0. Ahmed 9h, Mona 8h."
    log = _tracker()._parse_with_regex(note, site="S", date="2026-08-02")
    assert log.ppc == 0.88
    assert log.ncr_count == 2
    assert log.equipment_oee == 0.96
    assert log.lti_count == 0


def test_arabic_digit_normalization():
    note = "نسبة الإنجاز ٨٢٪. عدم مطابقة: ٠. كفاءة المعدات ٩٧٪. إصابات ٠."
    log = _tracker()._parse_with_regex(note, site="S", date="2026-08-02")
    assert log.ppc == 0.82
    assert log.ncr_count == 0
    assert log.equipment_oee == 0.97
    assert log.lti_count == 0


def test_staff_single_token_names_only():
    # Regression: prose must not be swept into a staff name.
    note = "LTI 1 - minor hand injury lost time reported. Sara 8h. Ahmed 9h."
    log = _tracker()._parse_with_regex(note, site="S", date="2026-08-02")
    names = {a.name for a in log.staff_allocations}
    assert "Sara" in names
    assert "Ahmed" in names
    # No multi-word sentence fragment captured as a name.
    assert all(" " not in n for n in names)
    assert not any("injury" in n.lower() for n in names)


def test_staff_hours_values():
    note = "Ahmed 9h, Mona 8h, Khaled 10h."
    log = _tracker()._parse_with_regex(note, site="S", date="2026-08-02")
    hours = {a.name: a.hours for a in log.staff_allocations}
    assert hours["Ahmed"] == 9.0
    assert hours["Khaled"] == 10.0


def test_aggregate_safety_gate_fails_on_lti():
    t = _tracker()
    logs = [
        t._parse_with_regex("PPC 90%. LTI 0. Ahmed 8h.", "A", "2026-08-02"),
        t._parse_with_regex("PPC 85%. LTI 1. Mona 8h.", "B", "2026-08-02"),
    ]
    agg = t.aggregate(logs)
    assert agg["total_lti"] == 1
    assert agg["safety_pass"] is False


def test_aggregate_ppc_average_and_gate():
    t = _tracker()
    logs = [
        t._parse_with_regex("PPC 90%. LTI 0.", "A", "2026-08-02"),
        t._parse_with_regex("PPC 80%. LTI 0.", "B", "2026-08-02"),
    ]
    agg = t.aggregate(logs)
    assert agg["avg_ppc"] == pytest.approx(0.85)
    assert agg["safety_pass"] is True


def test_staff_hours_rollup_across_sites():
    t = _tracker()
    notes = [
        {"site": "A", "date": "2026-08-02", "note": "Ahmed 9h."},
        {"site": "B", "date": "2026-08-02", "note": "Ahmed 4h."},
    ]
    res = t.run(notes)
    assert res["aggregate"]["staff_hours"]["Ahmed"] == 13.0


def test_digest_markdown_has_brand():
    res = _tracker().run([{"site": "A", "date": "2026-08-02", "note": "PPC 90%. LTI 0."}])
    assert "United Brothers Co." in res["digest_md"]
    assert "CEO Daily Site Digest" in res["digest_md"]
