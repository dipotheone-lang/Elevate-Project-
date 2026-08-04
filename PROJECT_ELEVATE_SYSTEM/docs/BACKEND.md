# PROJECT ELEVATE — Backend (persistence, reconciliation, escalations)
### United Brothers Co. / الاخوة المتحدين للمقاولات

Phase 2 makes the portfolio "real": a persistence store, the engine's safety
reconciliation, a period-close flow, and an escalation queue — implementing
PORT_GUIDE §5–§7. No new dependencies (`sqlite3` is stdlib).

---

## `portfolio_store.py` — SQLite persistence (§6)
One row per **(project, period)** plus a **projects** table and an
**escalations** log. On first use the DB is **seeded from `portfolio_data`**
(the authored history), so the dashboard looks identical until real periods are
closed on top of it.

**Tables**
- `projects` — id, name (EN/AR), code, region, members, handover dates.
- `periods` — verdict, net savings, team pool, unlocked, immediate/retained,
  blocked + cause, cash %, avg PPC/OEE, NCR, LTI, members paid, `closed_at`,
  workbook path. **Closed periods are immutable** by design.
- `escalations` — project, period, cause, owner, channel, amount, due, status.

**Read API** (returns the same dict shapes the dashboard uses):
`projects()`, `project(pid)`, `period_row(pid, pk)`, `portfolio_totals(pk)`.

**Write API**:
- `close_period(pid, pk, gs_result=, site_agg=)` — derives verdict / blocked /
  cause via the governance helpers, writes the immutable summary row, and
  **queues an escalation** (owner + channel from the rate schedule).
- `escalation_queue(pk)` / `mark_escalation_sent(id)`.

### Two interchangeable backends
The store picks its backend at connect time from configuration — the read/write
API is identical either way.

| Backend | When | Config | Durable on Streamlit Cloud? |
|---|---|---|---|
| **SQLite** | default, zero-config | `ELEVATE_DB` (default `./elevate.db`, gitignored) | ❌ ephemeral FS resets each redeploy |
| **Postgres / Supabase** | set a connection URL | `ELEVATE_DATABASE_URL` (or `DATABASE_URL`) | ✅ survives redeploys |

```bash
# Local / self-hosted SQLite on a mounted volume
export ELEVATE_DB=/data/elevate.db

# Durable managed Postgres / Supabase (survives Cloud redeploys)
export ELEVATE_DATABASE_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME"
```
On **Streamlit Community Cloud** put the URL in **secrets** (`ELEVATE_DATABASE_URL`
under *App → Settings → Secrets*), not in the repo. Use Supabase's **pooled**
(pgBouncer, port 6543) connection string for serverless-style redeploys.

The SQL is written once and adapted per backend (placeholders `?`→`%s`,
`INSERT OR REPLACE`→`ON CONFLICT … DO UPDATE`, `AUTOINCREMENT`→`BIGSERIAL`,
money columns `REAL`→`DOUBLE PRECISION`). `psycopg` is imported **only** when a
Postgres URL is present, so the SQLite path stays dependency-free. First connect
seeds the authored history into whichever backend is empty.

> ✅ Verified: with `ELEVATE_DATABASE_URL` set, a closed period and its queued
> escalation survive a fresh connection (the redeploy scenario). See the live
> round-trip test below.

---

## Safety reconciliation (engine, §7)
`gainsharing_calculator.safety_unreconciled(declared_lti, site_lti)` and
`reconcile_safety(fin, site_aggregate)` flag the case the design caught: the
site log reports **more LTIs than the safety-gate input was told about**. When
that happens the payout was computed as if the site were safe while the log says
otherwise — a confirmed LTI voids the whole pool. The dashboard surfaces this as
the **top-risk strip** and a warning on the Site KPIs tab.

---

## Escalation owners & handover (governance config, §5)
Lives in `target_rates.json → portfolio_governance` (and mirrored in
`portfolio_data` for the store):
```json
"escalation_owners": {
  "safety": {"owner": "HSE Manager", "channels": ["whatsapp","email"], "sla_days": 5},
  "cash":   {"owner": "Commercial",  "channels": ["email"],            "sla_days": 30},
  "gate":   {"owner": "Commercial",  "channels": ["email"],            "sla_days": 30}
},
"handover_dates": { "p1": "2027-03-01", ... },
"concentration_cap_pct": 0.40
```

---

---

## `escalation_sender.py` — real delivery (§5.2)
Turns a queued escalation into an actual notification:

- **email** → SMTP (stdlib `smtplib` / `email`)
- **whatsapp** → WhatsApp Business Cloud API (Meta Graph API, stdlib `urllib`)

`send(row)` dispatches on the row's `channel` and always returns a result dict
`{channel, to, status, detail}` — it never raises. `store.send_escalation(id)`
calls it and records the outcome (`status` → `sent` / `error`, plus the provider
detail and a timestamp); `store.send_queued(pk)` sends every still-queued row.

**Safe by default (dry-run).** With no credentials the sender runs in
**simulated** mode — it composes the message but does *not* touch the network,
so CI, offline runs and the public demo never send. The identical code path goes
live the instant credentials are present. No new dependencies (stdlib only).

**Credentials — from env / Streamlit secrets, never the repo:**
```bash
# Email (SMTP)
export SMTP_HOST=smtp.example.com SMTP_PORT=587
export SMTP_USER=... SMTP_PASSWORD=... SMTP_FROM="elevate@yourco.com"
export SMTP_STARTTLS=true          # default
# WhatsApp Business Cloud API
export WHATSAPP_TOKEN=...          # Meta Graph API token
export WHATSAPP_PHONE_ID=...       # sender phone-number id
export WHATSAPP_API_VERSION=v21.0  # default
```
**Recipients** (owner → address) live in `portfolio_data.ESCALATION_CONTACTS`
(mirrored in `target_rates.json → portfolio_governance.escalation_contacts`).
An empty channel value simply skips that channel; a configured channel with no
address on file is reported as `skipped`/`error` so misconfiguration is visible.

---

## `auth.py` — login + server-side roles (§5.1)
Turns the demo **role selector** into a real identity boundary using Streamlit's
built-in **OIDC** login (`st.login` / `st.user` / `st.logout`, Streamlit ≥ 1.42) —
works with any provider (Google Workspace, Microsoft Entra, Auth0, Okta).

- When an `[auth]` section is configured the app **requires sign-in** and derives
  the viewer's role **from their authenticated email** (`role_for(email)`), so the
  role can no longer be self-selected. Tab scoping (`ROLE_TABS`) becomes genuine
  server-side access control. Unmapped users fall back to the **least-privilege**
  `member` role.
- **Safe by default.** With no `[auth]` section, `auth.enabled()` is `False` and
  the app runs in demo mode with the role selector — local runs, the public demo
  and CI smoke tests work with zero config (same posture as the sender / store).

**Configuration — Streamlit secrets, never the repo:**
```toml
[auth]
redirect_uri = "https://your-app.streamlit.app/oauth2callback"
cookie_secret = "a-long-random-string"
client_id = "…"
client_secret = "…"
server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"
default_role = "member"

[roles]                       # email -> exec | mgr | member
"ceo@ubcsis.com" = "exec"
"pm.sokhna@ubcsis.com" = "mgr"
```
In the top bar an authenticated session shows an **identity chip** (name · role)
and a **Sign out** button instead of the role dropdown.

---

## In the dashboard
- **Portfolio** reads projects / totals / period matrix from the **store**, and
  shows the **escalation queue** with a **Send queued escalations** action. A
  caption tells the operator whether sending is *live* (credentials detected) or
  *dry-run*; failures surface inline (queue row shows **failed** in brick red).
- **Executive** (Exec/PM) gains **🔒 Close & persist period**, which writes the
  immutable summary and queues escalations.
- **Role** comes from the authenticated identity when OIDC is configured (demo
  selector otherwise).

## Tests
`tests/test_backend.py` — seeding, reads, `portfolio_totals`, blocking-cause
precedence, unlock forecast, `safety_unreconciled` / `reconcile_safety`, and the
close→persist→queue→sent flow (10 tests). `tests/test_escalation_sender.py` —
composition, dry-run defaults, mocked SMTP + WhatsApp send / skip / error paths,
and store wiring (12 tests). `tests/test_store_backends.py` — backend selection,
placeholder translation, per-backend DDL / upsert SQL, plus an **opt-in live
Postgres round-trip** (10 tests + 1 skipped). `tests/test_auth.py` — role
derivation, case-insensitivity, least-privilege fallback, invalid-role rejection
(7 tests). Full suite: **86 passing**.

Run the live Postgres test against any real database (e.g. Supabase):
```bash
export ELEVATE_PG_TEST_URL="postgresql://USER:PASSWORD@HOST:5432/DBNAME"
pytest tests/test_store_backends.py::test_live_postgres_roundtrip
```

---

_United Brothers Co. — PROJECT ELEVATE • Navy `#1B365D` / Gold `#D4AF37` / Brick `#B93429`_
