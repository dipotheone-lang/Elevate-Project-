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

Durability
----------
Two interchangeable backends, chosen at connect time:

* **SQLite** (default, zero-config). ``ELEVATE_DB`` points at the file
  (default ``./elevate.db``). Great locally / self-hosted with a mounted volume,
  but on Streamlit Community Cloud the filesystem is ephemeral — the file resets
  on each redeploy, so closed periods don't survive there.
* **Postgres / Supabase** (durable). Set ``ELEVATE_DATABASE_URL`` (or
  ``DATABASE_URL``) to a ``postgresql://…`` connection string — e.g. the pooled
  Supabase connection string — and closed periods persist across redeploys. The
  SQL is written once and adapted per backend; the read/write API is identical.

Credentials come from the environment / Streamlit secrets, never the repo.

Python: 3.10+  (sqlite3 is stdlib; ``psycopg`` is only imported when a Postgres
URL is configured).
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
_CONN: Optional["_Conn"] = None
_BACKEND = "sqlite"
_FORCE_SQLITE = False  # set when reset() is given an explicit file path (tests)


# --------------------------------------------------------------------------- #
#  Backend selection
# --------------------------------------------------------------------------- #
def _database_url() -> Optional[str]:
    """Postgres/Supabase URL from env, then Streamlit secrets. None ⇒ SQLite."""
    if _FORCE_SQLITE:
        return None
    for key in ("ELEVATE_DATABASE_URL", "DATABASE_URL"):
        val = os.environ.get(key)
        if val:
            return val
    try:  # optional — absent in CI / offline
        import streamlit as st

        for key in ("ELEVATE_DATABASE_URL", "DATABASE_URL"):
            if key in st.secrets:  # type: ignore[operator]
                v = st.secrets[key]
                if v:
                    return str(v)
    except Exception:  # pragma: no cover - streamlit absent / no secrets file
        pass
    return None


def backend() -> str:
    """'postgres' or 'sqlite' — reflects the connection that will be used."""
    url = _database_url()
    return "postgres" if (url and url.split(":", 1)[0] in ("postgres", "postgresql")) else "sqlite"


class _Conn:
    """Thin wrapper giving SQLite and psycopg a single interface. It translates
    ``?`` placeholders to ``%s`` for Postgres so the rest of the module writes
    portable SQL and reads rows by column name on both backends."""

    def __init__(self, raw, kind: str):
        self.raw = raw
        self.kind = kind

    def execute(self, sql: str, params: tuple = ()):  # noqa: ANN201
        if self.kind == "postgres":
            sql = sql.replace("?", "%s")
        return self.raw.execute(sql, params)

    def commit(self) -> None:
        self.raw.commit()

    def close(self) -> None:
        self.raw.close()


# --------------------------------------------------------------------------- #
#  Schema (adapted per backend)
# --------------------------------------------------------------------------- #
def _schema_statements(kind: str) -> list[str]:
    # SQLite REAL is 4-byte; use DOUBLE PRECISION on Postgres to keep money exact.
    real = "REAL" if kind == "sqlite" else "DOUBLE PRECISION"
    esc_pk = "id INTEGER PRIMARY KEY AUTOINCREMENT" if kind == "sqlite" else "id BIGSERIAL PRIMARY KEY"
    return [
        """CREATE TABLE IF NOT EXISTS projects (
            project_id   TEXT PRIMARY KEY,
            name         TEXT, name_ar   TEXT,
            code         TEXT, region    TEXT, region_ar TEXT,
            members      INTEGER,
            handover_en  TEXT, handover_ar TEXT
        )""",
        f"""CREATE TABLE IF NOT EXISTS periods (
            project_id        TEXT, period_key TEXT,
            verdict           TEXT,
            net_savings_egp   {real}, team_pool_raw_egp {real}, unlocked_pool_egp {real},
            immediate_70_egp  {real}, retained_30_egp   {real},
            blocked_egp       {real}, blocking_cause    TEXT,
            cash_collected_pct {real}, avg_ppc {real}, avg_oee {real},
            total_ncr INTEGER, total_lti INTEGER,
            members_total INTEGER, members_paid INTEGER,
            closed_at TEXT, workbook_path TEXT,
            PRIMARY KEY (project_id, period_key)
        )""",
        f"""CREATE TABLE IF NOT EXISTS escalations (
            {esc_pk},
            project_id TEXT, period_key TEXT,
            cause TEXT, owner TEXT, channel TEXT,
            amount {real}, due TEXT, status TEXT, created_at TEXT,
            send_detail TEXT, sent_at TEXT
        )""",
    ]


# Columns added after the first schema shipped; applied to pre-existing DBs.
_MIGRATIONS = {"escalations": ["send_detail TEXT", "sent_at TEXT"]}


def _upsert(conn: "_Conn", table: str, columns: list[str], values: tuple,
            conflict: list[str]) -> None:
    """Backend-appropriate insert-or-replace on the given conflict key(s)."""
    collist = ", ".join(columns)
    placeholders = ", ".join("?" for _ in columns)
    if conn.kind == "sqlite":
        sql = f"INSERT OR REPLACE INTO {table} ({collist}) VALUES ({placeholders})"
    else:
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in columns if c not in conflict)
        sql = (f"INSERT INTO {table} ({collist}) VALUES ({placeholders}) "
               f"ON CONFLICT ({', '.join(conflict)}) DO UPDATE SET {updates}")
    conn.execute(sql, values)


# --------------------------------------------------------------------------- #
#  Connection / schema / seed
# --------------------------------------------------------------------------- #
def _connect() -> "_Conn":
    global _CONN, _BACKEND
    if _CONN is None:
        _BACKEND = backend()
        if _BACKEND == "postgres":
            try:
                import psycopg
                from psycopg.rows import dict_row
            except ImportError as exc:  # pragma: no cover - depends on install
                raise RuntimeError(
                    "A Postgres URL is configured but the 'psycopg' driver is not "
                    "installed. Add 'psycopg[binary]' to requirements.") from exc
            raw = psycopg.connect(_database_url(), autocommit=False, row_factory=dict_row)
            _CONN = _Conn(raw, "postgres")
        else:
            raw = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            raw.row_factory = sqlite3.Row
            _CONN = _Conn(raw, "sqlite")
        for stmt in _schema_statements(_BACKEND):
            _CONN.execute(stmt)
        _migrate(_CONN)
        _CONN.commit()
        if not _CONN.execute("SELECT 1 FROM projects LIMIT 1").fetchone():
            _seed(_CONN)
    return _CONN


def _migrate(conn: "_Conn") -> None:
    """Add columns introduced after the initial schema to a pre-existing DB."""
    for table, cols in _MIGRATIONS.items():
        if conn.kind == "sqlite":
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for coldef in cols:
                if coldef.split()[0] not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {coldef}")
        else:
            for coldef in cols:  # Postgres supports IF NOT EXISTS
                conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {coldef}")
    conn.commit()


def _seed(conn: "_Conn") -> None:
    """Populate an empty DB from the authored history in portfolio_data."""
    proj_cols = ["project_id", "name", "name_ar", "code", "region", "region_ar",
                 "members", "handover_en", "handover_ar"]
    for p in pdata.PROJECTS:
        ho = pdata.HANDOVER.get(p["id"], {"en": "", "ar": ""})
        _upsert(conn, "projects", proj_cols,
                (p["id"], p["name"], p["nameAr"], p["code"], p["region"], p["regionAr"],
                 p["members"], ho["en"], ho["ar"]),
                conflict=["project_id"])
        for row in p["periods"]:
            _upsert_period_row(conn, p["id"], row)
    conn.commit()


def _upsert_period_row(conn: "_Conn", pid: str, row: dict) -> None:
    """Insert an authored/seed period row (only the fields the seed carries)."""
    cols = ["project_id", "period_key", "verdict", "net_savings_egp", "immediate_70_egp",
            "blocked_egp", "blocking_cause", "cash_collected_pct", "avg_ppc"]
    _upsert(conn, "periods", cols,
            (pid, row["k"], row["v"], row.get("s"), row.get("r"),
             row.get("b", 0), row.get("cs"),
             (row.get("c") / 100 if row.get("c") is not None else None),
             (row.get("p") / 100 if row.get("p") is not None else None)),
            conflict=["project_id", "period_key"])


def reset(db_path: str | Path | None = None) -> None:
    """Testing/utility: drop the cached connection and (optionally) repoint the
    SQLite file. Passing an explicit path forces the SQLite backend, so tests are
    never diverted to a Postgres URL that happens to be in the environment."""
    global _CONN, DB_PATH, _FORCE_SQLITE
    with _LOCK:
        if _CONN is not None:
            _CONN.close()
            _CONN = None
        if db_path is not None:
            DB_PATH = Path(db_path)
            _FORCE_SQLITE = True


# --------------------------------------------------------------------------- #
#  Read API  (returns the same dict shapes the dashboard/helpers expect)
# --------------------------------------------------------------------------- #
def _period_dict(r: Any) -> dict:  # sqlite3.Row or psycopg dict_row — name access
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

    period_cols = ["project_id", "period_key", "verdict", "net_savings_egp",
                   "team_pool_raw_egp", "unlocked_pool_egp", "immediate_70_egp",
                   "retained_30_egp", "blocked_egp", "blocking_cause",
                   "cash_collected_pct", "avg_ppc", "avg_oee", "total_ncr",
                   "total_lti", "members_total", "members_paid", "closed_at",
                   "workbook_path"]
    conn = _connect()
    with _LOCK:
        _upsert(conn, "periods", period_cols,
                (pid, pk, verdict, float(pool["net_savings_S_egp"]), float(pool["team_pool_raw_egp"]),
                 float(pool["unlocked_pool_egp"]), float(pool["immediate_70_egp"]),
                 float(pool["retained_30_egp"]), blocked, cause,
                 float(pool["cash_collected_pct"]), (site_agg.get("avg_ppc")),
                 (site_agg.get("avg_oee")), int(site_agg.get("total_ncr", 0)),
                 int(site_agg.get("total_lti", 0)), len(dist), members_paid, ts, workbook_path),
                conflict=["project_id", "period_key"])
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


def send_escalation(esc_id: int, sender=None) -> dict:
    """Actually deliver a queued escalation (email / WhatsApp) and record the
    outcome. Delegates transport to ``escalation_sender.send`` (overridable via
    ``sender`` for tests). When the channel is unconfigured the sender runs in
    simulated dry-run mode, so this is always safe offline / in CI.

    Status mapping: ``sent``/``simulated`` → ``'sent'``; ``skipped``/``error`` →
    ``'error'`` (surfaced in the queue so misconfiguration is visible). The
    provider detail is stored alongside for audit.
    Returns the sender's result dict."""
    if sender is None:
        import escalation_sender  # local import: keeps the store importable
        sender = escalation_sender.send  # even if the sender module is absent

    conn = _connect()
    r = conn.execute("SELECT * FROM escalations WHERE id=?", (esc_id,)).fetchone()
    if r is None:
        return {"status": "error", "detail": f"no escalation id={esc_id}"}

    result = sender(dict(r))
    status = "sent" if result.get("status") in ("sent", "simulated") else "error"
    detail = f"{result.get('status')}: {result.get('detail', '')}".strip()
    ts = datetime.now(timezone.utc).isoformat()
    with _LOCK:
        conn.execute("UPDATE escalations SET status=?, send_detail=?, sent_at=? WHERE id=?",
                     (status, detail, ts, esc_id))
        conn.commit()
    return result


def mark_escalation_sent(esc_id: int) -> dict:
    """Backward-compatible alias — sends the escalation for real (dry-run when
    the channel is unconfigured) and returns the sender result."""
    return send_escalation(esc_id)


def send_queued(pk: str | None = None, sender=None) -> list[dict]:
    """Send every still-queued escalation for a period. Returns per-row results."""
    out = []
    for e in escalation_queue(pk):
        if e["status"] == "queued":
            out.append(send_escalation(e["id"], sender=sender))
    return out
