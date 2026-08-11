# CLAUDE.md

Guidance for AI assistants (Claude Code and similar) working in this repository.

## What this repository is

**PROJECT ELEVATE** — an internal 80/20 gainsharing, KPI/L&D, and operational
automation system for United Brothers Co. (الاخوة المتحدين للمقاولات), an
Egyptian construction contractor. It audits supplier quotes against target
rates, tracks daily site KPIs, computes a governed team bonus pool, and emits
branded Excel/Markdown artifacts plus a Streamlit dashboard. All user-facing
output is **bilingual English/Arabic** and uses the corporate brand palette.

All application code lives in `PROJECT_ELEVATE_SYSTEM/`. The repo root holds
only deployment/infra files (`requirements.txt` for Streamlit Community Cloud,
`.streamlit/config.toml`, `.devcontainer/`, `.github/workflows/ci.yml`).

## Repository layout

```
Elevate-Project-/
├── requirements.txt              # Streamlit Cloud installs from THIS file — keep dashboard deps here
├── .streamlit/config.toml        # dashboard theme (gold primary, navy text)
├── .github/workflows/ci.yml     # CI: pytest matrix + pipeline smoke run
└── PROJECT_ELEVATE_SYSTEM/       # ← all source code; cd here to work
    ├── boq_auditor.py            # supplier-quote audit: PPV, unapproved scope, VE flags
    ├── site_tracker.py           # daily site notes (EN/AR) → PPC, NCR, OEE, LTI, staff hours
    ├── gainsharing_calculator.py # financial engine: savings, cash gate, 80/20 & 70/30 splits
    ├── export_excel_template.py  # branded 5-sheet workbook with live Excel formulas
    ├── run_pipeline.py           # A→Z orchestrator; writes ./outputs/
    ├── dashboard.py              # Streamlit app (Portfolio/Executive/Team/BOQ/Site/Downloads)
    ├── portfolio_data.py         # authored portfolio history + brand palette + governance helpers
    ├── portfolio_store.py        # SQLite persistence: period close, escalation queue
    ├── target_rates.json         # ← single config: target rates AND all governance constants
    ├── requirements*.txt         # core / -dashboard / -dev (pytest) / -optional (anthropic)
    ├── run.sh / run.bat          # one-command launchers (venv + deps + pipeline)
    ├── dashboard.sh / dashboard.bat
    ├── sample_inputs/            # ready-to-run supplier_quote.txt, site_notes.json
    ├── docs/                     # HOW_IT_WORKS.md (read first), BACKEND.md, DEPLOY.md
    └── tests/                    # pytest suite (57 tests)
```

## Common commands

Run everything from inside `PROJECT_ELEVATE_SYSTEM/`:

```bash
cd PROJECT_ELEVATE_SYSTEM
pip install -r requirements-dev.txt      # core deps + pytest + streamlit

python3 -m pytest tests/ -v              # full suite — 57 tests, ~3s
python3 -m pytest tests/test_gainsharing.py -v   # one module
python3 -m py_compile *.py               # syntax check (CI does this too)

python3 run_pipeline.py                  # full A→Z pipeline → ./outputs/
python3 gainsharing_calculator.py        # engine demo (prints worked example)
streamlit run dashboard.py               # dashboard at http://localhost:8501

python3 boq_auditor.py --quote sample_inputs/supplier_quote.txt \
        --supplier "Delta Supplies" --project "Tower B" --out outputs/boq.md
python3 site_tracker.py --notes sample_inputs/site_notes.json \
        --period "2026-08" --out outputs/digest.md
python3 export_excel_template.py --live --out outputs/MASTER.xlsx
```

There is no linter/formatter configured — CI runs only `py_compile`, pytest,
and a pipeline smoke run (`python run_pipeline.py --out /tmp/...`) on Python
3.10/3.11/3.12.

## Architecture

**Data flow:** supplier quotes → `boq_auditor` · site notes → `site_tracker` ·
financials → `gainsharing_calculator` → `export_excel_template` (workbook).
`run_pipeline.py` orchestrates all four stages; each stage degrades gracefully
(one failure never blocks the others; exit code is non-zero if any failed).
`dashboard.py` wraps the same modules in a Streamlit UI backed by
`portfolio_store.py` (SQLite).

Key design points:

- **`target_rates.json` is the single source of truth** for item target rates
  *and* every governance constant (pool splits, cash-gate tiers, L&D badge
  multipliers, safety limits, escalation owners, material escalation index).
  Rule tuning happens there, not in code. All modules load it.
- **AI parsing is optional.** `boq_auditor.py` and `site_tracker.py` use the
  Anthropic API (model `claude-3-7-sonnet-20250219`, needs `ANTHROPIC_API_KEY`
  + `pip install -r requirements-optional.txt`) to parse messy free-text, and
  **always fall back to deterministic regex parsers** when the key is absent or
  the call fails. Never make the API path mandatory; tests rely on the regex
  path. The regex parsers normalize Arabic-Indic digits (٠١٢٣…).
- **`gainsharing_calculator.py` is deterministic and side-effect-free.** It
  takes `ProjectFinancials` + `TeamMember` list and returns a
  `GainsharingResult` with three DataFrames: `pool_df`, `distribution_df`, and
  `audit_df` (every calculation step, for dispute resolution). Keep it that
  way — no I/O, no network.
- **The Excel workbook stays formula-driven.** `ElevateWorkbookBuilder` seeds
  values but all derived cells remain live Excel formulas (`SUM`/`IF`/`AND`),
  so the workbook recalculates and totals reconcile to line items to the cent.
  Don't replace formulas with hardcoded computed values.
- **`portfolio_store.py`** (stdlib `sqlite3`, no new dependency) keeps one row
  per (project, period), seeds itself from `portfolio_data.py` on first use,
  and exposes read APIs returning the same dict shapes the dashboard consumes.
  **Closed periods are immutable by design.** DB path via `ELEVATE_DB` env var
  (default `./elevate.db`, gitignored).
- **Safety reconciliation:** `safety_unreconciled()` / `reconcile_safety()` in
  the engine flag when the site log reports more LTIs than the safety-gate
  input declared — a confirmed LTI voids the whole pool. The dashboard surfaces
  this as the top-risk strip.
- **Dashboard charts are HTML/CSS** (deliberately, to avoid Plotly font/DPI
  drift on projectors), even though Plotly is installed.

### Governance rules (implemented in `gainsharing_calculator.py`, tuned in `target_rates.json`)

```
S       = max(0, adjusted_baseline − actual − bad_debt) × F_quality
P_pool  = S × 0.35                       (35% team / 65% company)
Cash gate: ≥85% → 100% · 75–85% → pro-rata (collected/0.85) · <75% → holdback
Splits : 80% base equal pool / 20% performance pool; 70% immediate / 30% retained
L&D    : L1 ×1.0 · L2 ×1.2 · L3 ×1.35
Gates  : PPC ≥ 85% · OEE > 95% · zero LTI (any LTI DQs the whole team)
Scope  : line total > 10,000 EGP without approved VO → unapproved-scope flag
```

## Conventions

- **Python 3.10+**, type hints, `from __future__ import annotations`,
  dataclasses for data models. Modules open with a docstring naming the
  company (EN/AR) and the module's purpose.
- **Bilingual output**: user-facing reports, dashboard labels, and data
  structures carry EN and AR strings (often `name` / `name_ar`, or
  `{"en": ..., "ar": ...}` dicts). Preserve this when adding features.
- **Brand palette** (canonical constants at top of `portfolio_data.py`):
  navy `#1B365D`, gold `#D4AF37`, brick red `#B93429` (crisis), green
  `#2E7D32` / fill `#E8F5E9` (approved), amber `#EF6C00` / fill `#FFF3E0`
  (warning). Use these in any new report/UI/workbook styling.
- **Currency is EGP** throughout; percentages are stored as fractions
  (`0.85`, not `85`).
- **Every governance-rule change needs a test** in `tests/` — CI enforces the
  suite on every push/PR to `main`. Tests use the regex parsers (no API key)
  and pathlib/tempfile for outputs.
- **Generated artifacts are gitignored** (`outputs/`, `*.xlsx`, `*_report.md`,
  `*_digest.md`, `elevate.db`). Never commit them.
- Dependency files are layered: `PROJECT_ELEVATE_SYSTEM/requirements.txt`
  (core), `-dashboard` (adds streamlit/plotly), `-dev` (adds pytest),
  `-optional` (anthropic). The **repo-root** `requirements.txt` mirrors the
  dashboard deps because Streamlit Community Cloud installs from the root —
  keep root and `-dashboard`/core files in sync when adding a dependency.

## Extending the system

- New BOQ items/rates → add to `target_rates[]` in `target_rates.json`.
- New commodity escalation → `material_escalation_index` in the same file.
- Re-tune a rule (e.g. PPC gate) → edit `governance` in the same file.
- New site KPI → extend `site_tracker.py`'s parsers + `SiteLog` + digest.
- New payout factor → extend `TeamMember` + `distribute()` + a test.

## Documentation to keep updated

`PROJECT_ELEVATE_SYSTEM/docs/HOW_IT_WORKS.md` is the canonical A→Z walkthrough
(data flow, period lifecycle, every formula with a worked example);
`docs/BACKEND.md` covers persistence/reconciliation/escalations;
`docs/DEPLOY.md` covers Streamlit Cloud deployment; `README.md` is the quick
start. When changing behavior, formulas, or module interfaces, update the
matching doc — they are written for non-technical stakeholders as well as
developers.
