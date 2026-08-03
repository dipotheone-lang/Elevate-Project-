# PROJECT ELEVATE — Bulletproof Enterprise Edition
### United Brothers Co. / الاخوة المتحدين للمقاولات

Internal **80/20 Gainsharing, Individual KPI / L&D Development, and Operational
Automation System** for United Brothers Co. — serving Suez, Ain Sokhna, Greater
Cairo, and the New Administrative Capital.

نظام المشاركة في المكاسب وتطوير الكفاءات وأتمتة العمليات — النسخة المؤسسية المحصنة.

> 📖 **New here? Read the full A→Z walkthrough:** [`docs/HOW_IT_WORKS.md`](docs/HOW_IT_WORKS.md)
> — data flow, the period lifecycle, every governance formula with a worked
> example, and how to run each part.

---

## 🚀 Quick Start (one command)

After [installing Python 3.10+](https://python.org/downloads) and downloading
this repo, open a terminal in the `PROJECT_ELEVATE_SYSTEM` folder and run:

| Platform | Run everything | Run the tests |
|---|---|---|
| **Mac / Linux** | `./run.sh` | `./run.sh test` |
| **Windows** | double-click `run.bat` (or `run.bat`) | `run.bat test` |

The launcher creates the virtual environment, installs dependencies, and runs
the full pipeline — results land in `./outputs/` (open
`UNITED_BROTHERS_ELEVATE_MASTER.xlsx` in Excel). Everything below is the manual
equivalent.

---

## 🎨 Corporate Theme
| Token | Value | Use |
|---|---|---|
| Navy Blue | `#1B365D` | Headers, accents (white bold text) |
| Industrial Gold | `#D4AF37` | Metrics, badges, totals |
| Approved | fill `#E8F5E9` / text `#2E7D32` | Full payout |
| Warning | fill `#FFF3E0` / text `#EF6C00` | SLA penalty |
| Crisis | fill `#FFEBEE` / text `#C62828` | Disqualified / hold |

---

## 📦 Modules

| File | Purpose (EN / AR) |
|---|---|
| `boq_auditor.py` | EGP BOQ & supplier-quote auditor — PPV, unapproved scope, VE. مدقق جداول الكميات |
| `site_tracker.py` | Daily WhatsApp/voice site log → PPC, NCR, OEE, LTI, staff hours + CEO digest. محرك السجل اليومي |
| `gainsharing_calculator.py` | Full financial engine — cash gate, 80/20, 70/30, L&D badges, safety gate. محرك المكاسب |
| `export_excel_template.py` | Branded `UNITED_BROTHERS_ELEVATE_MASTER.xlsx` generator. مولّد قالب إكسل |
| `run_pipeline.py` | End-to-end A→Z orchestrator running all four stages. المنسّق الكامل |
| `target_rates.json` | Master target-rate & governance schema. مخطط الأسعار والحوكمة |
| `tests/` | Pytest suite (45 tests) covering governance rules & I/O. مجموعة الاختبارات |

---

## ⚙️ Setup

```bash
# 1) Python 3.10+ virtual environment
python3 -m venv .venv && source .venv/bin/activate

# 2) Install core dependencies
pip install -r requirements.txt

# 3) (Optional) enable AI parsing for BOQ & site notes
pip install -r requirements-optional.txt          # anthropic SDK
export ANTHROPIC_API_KEY="sk-ant-..."             # uses claude-3-7-sonnet-20250219

# 4) (Dev) install test tooling
pip install -r requirements-dev.txt               # + pytest
```

> Without `ANTHROPIC_API_KEY`, `boq_auditor.py` and `site_tracker.py`
> automatically fall back to a deterministic regex parser — the system is fully
> operational offline.

---

## ▶️ Usage

```bash
# Run the WHOLE pipeline A → Z (BOQ → Site → Gainsharing → live workbook)
python3 run_pipeline.py            # writes everything into ./outputs/

# BOQ / quote audit → Markdown report
python3 boq_auditor.py --quote quote.txt --supplier "ACME Supplies" \
        --project "Suez Plant" --out boq_audit_report.md

# Daily site digest → Markdown (CEO)
python3 site_tracker.py --notes notes.json --period "2026-08-02" \
        --out site_daily_digest.md

# Gainsharing engine (demo / library)
python3 gainsharing_calculator.py

# Branded master workbook — blank template (editable demo rows)
python3 export_excel_template.py --out UNITED_BROTHERS_ELEVATE_MASTER.xlsx

# Branded master workbook — LIVE: Gainsharing & Pool sheets seeded from a real
# gainsharing_calculator run (formulas preserved, so it still recalculates)
python3 export_excel_template.py --live --out UNITED_BROTHERS_ELEVATE_MASTER.xlsx
```

> **Live workbook seeding.** `ElevateWorkbookBuilder(gainsharing_result=...)`
> accepts a `GainsharingResult` from the engine and seeds the Gainsharing
> (Base/Perf shares, SLA & L&D flags) and Pool & Cash Gate (baseline, Δ,
> actual, F_quality, bad debt, cash %) sheets with real figures. All
> derived cells stay formula-driven (`SUM`/`IF`/`AND`), so the workbook
> self-recalculates and reconciles line items to totals to the cent.

### `notes.json` shape (site_tracker)
```json
[
  {"site": "New Capital Tower B", "date": "2026-08-02", "note": "PPC 88%. NCR 1. OEE 96%. LTI 0. Ahmed 9h."}
]
```

### `quote.txt` shape (boq_auditor regex fallback)
```
# item_code | description | unit | qty | unit_rate_egp | approved_vo
CIV-CONC-C30 | Ready-mix concrete C30 | m3 | 250 | 2600 | no
```

Ready-to-run examples live in `sample_inputs/` (`supplier_quote.txt`, `site_notes.json`).

---

## ✅ Testing & CI

```bash
pip install -r requirements-dev.txt
python3 -m pytest tests/ -v        # 45 tests: governance rules, BOQ, site, Excel, pipeline
```

Every push and pull request to `main` runs the suite on Python 3.10/3.11/3.12
via GitHub Actions (`.github/workflows/ci.yml`), plus a smoke run of the full
pipeline.

---

## 🧮 Governance Formulas

```
C_adjusted_baseline = C_baseline + (C_baseline × Δ Material Escalation Index)
S                   = max(0, (C_adjusted_baseline − C_actual − BadDebt)) × F_quality
P_pool              = S × 0.35            (35% team / 65% company retention)

Cash Gate:  ≥85% → 100% unlock
            75–85% → pro-rata (P_pool × collected / 0.85)
            <75% → 100% holdback
Payout:     70% immediate / 30% retained cushion
Split:      80% base equal pool / 20% performance pool
L&D badge:  L1 ×1.0 · L2 ×1.2 · L3 ×1.35
Gates:      PPC ≥ 85% · OEE > 95% · Zero LTI (0) · Scope > 10,000 EGP needs VO
```

---

## 🔌 Programmatic API

```python
from gainsharing_calculator import GainsharingCalculator, ProjectFinancials, TeamMember

calc = GainsharingCalculator("target_rates.json")
result = calc.run(
    ProjectFinancials("Ain Sokhna WH", 12_000_000, 10_400_000,
                      cash_collected_pct=0.82, quality_factor=0.95,
                      escalation_commodity="steel_rebar", bad_debt_egp=150_000,
                      subcontractor_value_egp=3_000_000, lost_time_injuries=0),
    [TeamMember("Ahmed", "Site Manager", ld_badge="Level 3", ppc=0.92)],
)
print(result.pool_df, result.distribution_df, result.audit_df)
```

---

_United Brothers Co. — PROJECT ELEVATE • Navy `#1B365D` / Gold `#D4AF37`_
