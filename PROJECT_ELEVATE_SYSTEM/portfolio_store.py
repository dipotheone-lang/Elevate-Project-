#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
portfolio_store.py
==================
United Brothers Co. / الاخوة المتحدين للمقاولات
PROJECT ELEVATE — persistence backend (PORT_GUIDE §6)

A SQLite-backed store of one row per (project, period). It makes the Portfolio
tab, period switcher, sparklines, deltas, blocked-by-cause split and period
matrix *real* — driven by a database instead of hardcoded lists — and lets a
live period be **closed** (persisted, immutable) with its escalations queued.

On first use the DB is seeded from `portfolio_data` (the authored history), so
the dashboard looks identical until real periods are closed on top of it.

Durability note: on Streamlit Community Cloud the container filesystem is
ephemeral (it resets on each redeploy), so the SQLite file there is per-deploy.
Point `ELEVATE_DB` at a mounted volume / external path for durable persistence,
or run locally / self-hosted. The schema and API are production-shaped either way.

Python: 3.10+  (sqlite3 is stdlib — no new dependency)
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import portfolio_data as pdata

HERE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("ELEVATE_DB", HERE / "elevate.db"))

_LOCK = threading.Lock()
_CONN: Optional[sqlite3.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    project_id   TEXT PRIMARY KEY,
    name         TEXT, name_ar   TEXT,
    code         TEXT, region    TEXT, region_ar TEXT,
    members      INTEGER,
    handover_en  TEXT, handover_ar TEXT
);
CREATE TABLE IF NOT EXISTS periods (
    project_id        TEXT, period_key TEXT,
    verdict           TEXT,
    net_savings_egp   REAL, team_pool_raw_egp REAL, unlocked_pool_egp REAL,
    immediate_70_egp  REAL, retained_30_egp   REAL,
    blocked_egp       REAL, blocking_cause    TEXT,
    cash_collected_pct REAL, avg_ppc REAL, avg_oee REAL,
    total_ncr INTEGER, total_lti INTEGER,
    members_total INTEGER, members_paid INTEGER,
    closed_at TEXT, workbook_path TEXT,
    PRIMARY KEY (project_id, period_key)
);
CREATE TABLE IF NOT EXISTS escalations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT, period_key TEXT,
    cause TEXT, owner TEXT, channel TEXT,
    amount REAL, due TEXT, status TEXT, created_at TEXT
);
"""


# --------------------------------------------------------------------------- #
#  Connection / schema / seed
# --------------------------------------------------------------------------- #
def _connect() -> sqlite3.Connection:
    global _CONN
    if _CONN is None:
        _CONN = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _CONN.row_factory = sqlite3.Row
        _CONN.executescript(SCHEMA)
        _CONN.commit()
        if not _CONN.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
            _seed(_CONN)
    return _CONN


def _seed(conn: sqlite3.Connection) -> None:
    """Populate an empty DB from the authored history in portfolio_data."""
    for p in pdata.PROJECTS:
        ho = pdata.HANDOVER.get(p["id"], {"en": "", "ar": ""})
        conn.execute(
            "INSERT OR REPLACE INTO projects VALUES (?,?,?,?,?,?,?,?,?)",
            (p["id"], p["name"], p["nameAr"], p["code"], p["region"], p["regionAr"],
             p["members"], ho["en"], ho["ar"]))
        for row in p["periods"]:
            _upsert_period_row(conn, p["id"], row)
    conn.commit()


def _upsert_period_row(conn: sqlite3.Connection, pid: str, row: dict) -> None:
    """Insert an authored/seed period row (only the fields the seed carries)."""
    conn.execute("""INSERT OR REPLACE INTO periods
        (project_id, period_key, verdict, net_savings_egp, immediate_70_egp,
         blocked_egp, blocking_cause, cash_collected_pct, avg_ppc)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (pid, row["k"], row["v"], row.get("s"), row.get("r"),
         row.get("b", 0), row.get("cs"),
         (row.get("c") / 100 if row.get("c") is not None else None),
         (row.get("p") / 100 if row.get("p") is not None else None)))


def reset(db_path: str | Path | None = None) -> None:
    """Testing/utility: drop the in-memory connection and (optionally) the file."""
    global _CONN, DB_PATH
    with _LOCK:
        if _CONN is not None:
            _CONN.close()
            _CONN = None
        if db_path is not None:
            DB_PATH = Path(db_path)


# --------------------------------------------------------------------------- #
#  Read API  (returns the same dict shapes the dashboard/helpers expect)
# --------------------------------------------------------------------------- #
def _period_dict(r: sqlite3.Row) -> dict:
    return {
        "k": r["period_key"], "v": r["verdict"],
        "r": (int(r["immediate_70_egp"]) if r["immediate_70_egp"] is not None else None),
        "c": (round(r["cash_collected_pct"] * 100) if r["cash_collected_pct"] is not None else None),
        "p": (round(r["avg_ppc"] * 100) if r["avg_ppc"] is not None else None),
        "b": (r["blocked_egp"] or 0),
        "cs": r["blocking_cause"],
        "s": (int(r["net_savings_egp"]) if r["net_savings_egp"] is not None else None),
    }


def projects() -> list[dict]:
    """All projects with their period rows — same shape as portfolio_data.PROJECTS."""
    conn = _connect()
    order = [p["id"] for p in pdata.PROJECTS]
    out = []
    for pr in conn.execute("SELECT * FROM projects").fetchall():
        periods = [_period_dict(r) for r in conn.execute(
            "SELECT * FROM periods WHERE project_id=?", (pr["project_id"],)).fetchall()]
        periods.sort(key=lambda x: [q["k"] for q in pdata.PERIODS].index(x["k"]))
        paid = sum(1 for x in periods if x["r"])
        out.append({
            "id": pr["project_id"], "name": pr["name"], "nameAr": pr["name_ar"],
            "code": pr["code"], "region": pr["region"], "regionAr": pr["region_ar"],
            "members": pr["members"], "paid": paid, "periods": periods})
    out.sort(key=lambda p: order.index(p["id"]) if p["id"] in order else 99)
    return out


def project(pid: str) -> dict:
    return next(p for p in projects() if p["id"] == pid)


def period_row(pid: str, pk: str) -> dict:
    return next(x for x in project(pid)["periods"] if x["k"] == pk)


def portfolio_totals(pk: str) -> dict:
    """Aggregate released/savings/retained/paying/blocked for a period."""
    released = savings = retained = blocked = paying = 0
    blocked_rows = []
    for p in projects():
        row = next(x for x in p["periods"] if x["k"] == pk)
        if row["r"]:
            released += row["r"]; paying += 1
            retained += row["r"] / 0.70 * 0.30
        if row["s"]:
            savings += row["s"]
        if row.get("b"):
            blocked += row["b"]
            blocked_rows.append({"project": p, "row": row, "cause": row.get("cs")})
    blocked_rows.sort(key=lambda x: -x["row"]["b"])
    return {"released": released, "savings": savings, "retained": retained,
            "paying": paying, "blocked": blocked, "blocked_rows": blocked_rows}


# --------------------------------------------------------------------------- #
#  Write API — close a period (persist + queue escalations)
# --------------------------------------------------------------------------- #
def close_period(pid: str, pk: str, *, gs_result, site_agg: dict,
                 workbook_path: str = "", now: Optional[str] = None) -> dict:
    """Persist a computed period as CLOSED (immutable summary) and queue any
    escalation. Verdict / blocked / cause are derived via the governance helpers.
    Returns the stored summary dict."""
    pool = gs_result.pool_df.iloc[0]
    dist = gs_result.distribution_df
    cause = pdata.blocking_cause(pool["cash_gate_status"], gs_result.safety_disqualified)
    if gs_result.safety_disqualified:
        verdict, blocked = "DQ", float(pool["team_pool_raw_egp"])
    elif pool["cash_gate_status"] == "HOLDBACK":
        verdict, blocked = "HOLD", float(pool["team_pool_raw_egp"])
    elif pool["cash_gate_status"] == "PARTIAL_UNLOCK":
        verdict, blocked = "PARTIAL", float(pool["team_pool_raw_egp"] - pool["unlocked_pool_egp"])
    else:
        verdict, blocked = "FULL", 0.0
    members_paid = int((dist["gross_share_egp"] > 0).sum())
    ts = now or datetime.now(timezone.utc).isoformat()

    conn = _connect()
    with _LOCK:
        conn.execute("""INSERT OR REPLACE INTO periods
            (project_id, period_key, verdict, net_savings_egp, team_pool_raw_egp,
             unlocked_pool_egp, immediate_70_egp, retained_30_egp, blocked_egp,
             blocking_cause, cash_collected_pct, avg_ppc, avg_oee, total_ncr,
             total_lti, members_total, members_paid, closed_at, workbook_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (pid, pk, verdict, float(pool["net_savings_S_egp"]), float(pool["team_pool_raw_egp"]),
             float(pool["unlocked_pool_egp"]), float(pool["immediate_70_egp"]),
             float(pool["retained_30_egp"]), blocked, cause,
             float(pool["cash_collected_pct"]), (site_agg.get("avg_ppc")),
             (site_agg.get("avg_oee")), int(site_agg.get("total_ncr", 0)),
             int(site_agg.get("total_lti", 0)), len(dist), members_paid, ts, workbook_path))
        # Queue an escalation for a blocked outcome.
        conn.execute("DELETE FROM escalations WHERE project_id=? AND period_key=?", (pid, pk))
        if cause:
            cfg = pdata.ESCALATION_OWNERS.get(cause, {})
            for ch in cfg.get("channels", ["email"]):
                conn.execute("""INSERT INTO escalations
                    (project_id, period_key, cause, owner, channel, amount, due, status, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                    (pid, pk, cause, cfg.get("owner", "—"), ch, blocked,
                     pdata.CAUSE.get(cause, {}).get("due", ""), "queued", ts))
        conn.commit()
    return period_row(pid, pk)


def escalation_queue(pk: str | None = None) -> list[dict]:
    conn = _connect()
    q = "SELECT * FROM escalations"
    args: tuple = ()
    if pk:
        q += " WHERE period_key=?"; args = (pk,)
    q += " ORDER BY amount DESC"
    return [dict(r) for r in conn.execute(q, args).fetchall()]


def mark_escalation_sent(esc_id: int) -> None:
    conn = _connect()
    with _LOCK:
        conn.execute("UPDATE escalations SET status='sent' WHERE id=?", (esc_id,))
        conn.commit()
