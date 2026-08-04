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

**Configuration** — point `ELEVATE_DB` at a durable path:
```bash
export ELEVATE_DB=/data/elevate.db      # default: ./elevate.db (gitignored)
```

> ⚠️ **Streamlit Community Cloud** filesystems are ephemeral — the SQLite file
> resets on each redeploy, so closed periods there last only until the next
> deploy. For durable persistence, run locally / self-hosted with `ELEVATE_DB`
> on a mounted volume, or swap the store for a managed Postgres (the API is the
> same shape). The schema is production-ready either way.

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

## In the dashboard
- **Portfolio** reads projects / totals / period matrix from the **store**, and
  shows the **escalation queue** with a **Send queued escalations** action. A
  caption tells the operator whether sending is *live* (credentials detected) or
  *dry-run*; failures surface inline (queue row shows **failed** in brick red).
- **Executive** (Exec/PM) gains **🔒 Close & persist period**, which writes the
  immutable summary and queues escalations.

## Still open (real integrations)
- **Roles** come from a selector (demo); production should derive role from the
  auth layer with server-side row filtering (PORT_GUIDE §5.1).

## Tests
`tests/test_backend.py` — seeding, reads, `portfolio_totals`, blocking-cause
precedence, unlock forecast, `safety_unreconciled` / `reconcile_safety`, and the
close→persist→queue→sent flow (10 tests). `tests/test_escalation_sender.py` —
composition, dry-run defaults, mocked SMTP + WhatsApp send / skip / error paths,
and store wiring (12 tests). Full suite: **69 passing**.

---

_United Brothers Co. — PROJECT ELEVATE • Navy `#1B365D` / Gold `#D4AF37` / Brick `#B93429`_
