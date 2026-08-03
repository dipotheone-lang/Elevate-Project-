# -*- coding: utf-8 -*-
"""Smoke tests for the Streamlit dashboard using Streamlit's AppTest harness.
اختبارات لوحة التحكم.

Skipped automatically if Streamlit isn't installed (e.g. a core-only env)."""
import pytest

pytest.importorskip("streamlit")

from pathlib import Path
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "dashboard.py")


def test_dashboard_loads_without_exception():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert not at.exception, at.exception


def test_dashboard_run_button_produces_results():
    at = AppTest.from_file(APP, default_timeout=120)
    at.run()
    assert len(at.button) >= 1
    at.button[0].click().run()
    assert not at.exception, at.exception
    labels = [m.label for m in at.metric]
    # Core gainsharing + site KPIs should render after a run.
    assert any("savings" in l.lower() for l in labels)
    assert any("ppc" in l.lower() for l in labels)
    # The four download buttons (xlsx + 3 reports) should exist.
    assert len(at.get("download_button")) == 4
