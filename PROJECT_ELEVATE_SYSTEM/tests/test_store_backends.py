# -*- coding: utf-8 -*-
"""Backend-adaptation tests for portfolio_store: selection logic, placeholder
translation, and per-backend DDL / upsert SQL. These are pure-logic checks that
need no Postgres server, so they run everywhere (CI included). A live end-to-end
Postgres run is covered separately and opt-in via ELEVATE_PG_TEST_URL."""
import os

import pytest

import portfolio_store as store


# --------------------------------------------------------------------------- #
#  Backend selection
# --------------------------------------------------------------------------- #
def test_defaults_to_sqlite(monkeypatch):
    monkeypatch.delenv("ELEVATE_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(store, "_FORCE_SQLITE", False)
    assert store.backend() == "sqlite"


@pytest.mark.parametrize("url", [
    "postgresql://u:p@host:5432/db",
    "postgres://u:p@host/db",
])
def test_postgres_url_selects_postgres(monkeypatch, url):
    monkeypatch.setattr(store, "_FORCE_SQLITE", False)
    monkeypatch.setenv("ELEVATE_DATABASE_URL", url)
    assert store.backend() == "postgres"


def test_forced_sqlite_ignores_url(monkeypatch):
    # reset(path) sets _FORCE_SQLITE so tests never divert to a stray PG URL.
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@host/db")
    monkeypatch.setattr(store, "_FORCE_SQLITE", True)
    assert store.backend() == "sqlite"
    assert store._database_url() is None


# --------------------------------------------------------------------------- #
#  Placeholder translation (? -> %s only on Postgres)
# --------------------------------------------------------------------------- #
class _Recorder:
    def __init__(self):
        self.sql = None

    def execute(self, sql, params):
        self.sql = sql
        return self


def test_placeholder_translation_postgres():
    rec = _Recorder()
    conn = store._Conn(rec, "postgres")
    conn.execute("SELECT * FROM periods WHERE project_id=? AND period_key=?", ("p1", "jul"))
    assert rec.sql == "SELECT * FROM periods WHERE project_id=%s AND period_key=%s"


def test_placeholder_untouched_sqlite():
    rec = _Recorder()
    conn = store._Conn(rec, "sqlite")
    conn.execute("SELECT * FROM periods WHERE project_id=?", ("p1",))
    assert rec.sql == "SELECT * FROM periods WHERE project_id=?"


# --------------------------------------------------------------------------- #
#  Per-backend DDL
# --------------------------------------------------------------------------- #
def test_sqlite_schema_uses_autoincrement_and_real():
    ddl = " ".join(store._schema_statements("sqlite"))
    assert "AUTOINCREMENT" in ddl and "REAL" in ddl
    assert "BIGSERIAL" not in ddl and "DOUBLE PRECISION" not in ddl


def test_postgres_schema_uses_bigserial_and_double():
    ddl = " ".join(store._schema_statements("postgres"))
    assert "BIGSERIAL" in ddl and "DOUBLE PRECISION" in ddl
    assert "AUTOINCREMENT" not in ddl
    # money columns must not fall back to 4-byte REAL on Postgres
    assert " REAL" not in ddl


# --------------------------------------------------------------------------- #
#  Per-backend upsert SQL
# --------------------------------------------------------------------------- #
def test_upsert_sqlite_uses_insert_or_replace():
    rec = _Recorder()
    conn = store._Conn(rec, "sqlite")
    store._upsert(conn, "periods", ["project_id", "period_key", "verdict"],
                  ("p1", "jul", "FULL"), conflict=["project_id", "period_key"])
    assert rec.sql.startswith("INSERT OR REPLACE INTO periods")


def test_upsert_postgres_uses_on_conflict():
    rec = _Recorder()
    conn = store._Conn(rec, "postgres")
    store._upsert(conn, "periods", ["project_id", "period_key", "verdict"],
                  ("p1", "jul", "FULL"), conflict=["project_id", "period_key"])
    # translated placeholders + conflict clause updating only non-key columns
    assert "ON CONFLICT (project_id, period_key) DO UPDATE SET" in rec.sql
    assert "verdict=EXCLUDED.verdict" in rec.sql
    assert "project_id=EXCLUDED.project_id" not in rec.sql  # key not self-updated
    assert "?" not in rec.sql and "%s" in rec.sql


# --------------------------------------------------------------------------- #
#  Optional live Postgres end-to-end (opt-in): set ELEVATE_PG_TEST_URL
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(not os.environ.get("ELEVATE_PG_TEST_URL"),
                    reason="set ELEVATE_PG_TEST_URL to run the live Postgres round-trip")
def test_live_postgres_roundtrip(monkeypatch):
    from gainsharing_calculator import (GainsharingCalculator, ProjectFinancials,
                                         TeamMember)
    from conftest import RATES

    monkeypatch.setattr(store, "_FORCE_SQLITE", False)
    monkeypatch.setenv("ELEVATE_DATABASE_URL", os.environ["ELEVATE_PG_TEST_URL"])
    store.reset()  # drop cached conn; keep PG selection (no path -> not forced)
    store._FORCE_SQLITE = False
    try:
        assert store.backend() == "postgres"
        assert len(store.projects()) == 4
        assert store.period_row("p1", "jul")["v"] == "PARTIAL"
        fin = ProjectFinancials("T", 12_000_000, 10_400_000, cash_collected_pct=0.82,
                                quality_factor=0.95, escalation_commodity="steel_rebar",
                                bad_debt_egp=150_000, subcontractor_value_egp=3_000_000,
                                lost_time_injuries=0)
        gs = GainsharingCalculator(RATES).run(fin, [TeamMember("A", "SM", ppc=0.9)])
        store.close_period("p1", "jul", gs_result=gs, site_agg={"total_lti": 0})
        q = store.escalation_queue("jul")
        assert q and q[0]["status"] == "queued"
        assert store.send_escalation(q[0]["id"])["status"] == "simulated"
        assert store.escalation_queue("jul")[0]["status"] == "sent"
    finally:
        store.reset()
