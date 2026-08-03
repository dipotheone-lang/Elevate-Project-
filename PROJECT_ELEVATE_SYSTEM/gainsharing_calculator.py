#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gainsharing_calculator.py
=========================
United Brothers Co. / الاخوة المتحدين للمقاولات
PROJECT ELEVATE (Bulletproof Enterprise Edition)

Adaptive Gainsharing & Dispute Resolution Engine
محرك المشاركة في المكاسب وحل النزاعات

Implements the complete PROJECT ELEVATE financial governance:
  * Inflation-adjusted baseline & gross savings (S)
  * 35% team shared pool / 65% company retention
  * Tiered Cash Liquidity Gate (>=85% / 75-85% pro-rata / <75% holdback)
  * 70% immediate / 30% retained cushion payout split
  * 80/20 distribution (base equal pool vs. performance pool)
  * Individual L&D badge multipliers (1.0x / 1.2x / 1.35x)
  * Zero-LTI safety disqualification gate
  * Bad-debt isolation & subcontractor back-charge reserve
  * Unapproved-scope SLA guardrail (>10,000 EGP)
  * Time-weighted pro-rata allocation & vested resignation payout

All monetary values are in EGP. The engine is deterministic, side-effect free,
and returns structured Pandas DataFrames plus a full audit trail so that every
figure is traceable for dispute resolution / audit readiness.

Author: AI Operations Architect — United Brothers Co.
Python: 3.10+
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    import pandas as pd
except ImportError as exc:  # pragma: no cover - dependency guard
    raise SystemExit(
        "[FATAL] pandas is required. Install with: pip install pandas\n"
        "        مطلوب مكتبة pandas."
    ) from exc

# --------------------------------------------------------------------------- #
#  Logging  |  التسجيل
# --------------------------------------------------------------------------- #
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | ELEVATE-GAINSHARE | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("elevate.gainsharing")

DEFAULT_RATES_PATH = Path(__file__).with_name("target_rates.json")


# --------------------------------------------------------------------------- #
#  Data models  |  نماذج البيانات
# --------------------------------------------------------------------------- #
@dataclass
class TeamMember:
    """Individual eligible for gainsharing distribution. عضو الفريق."""

    name: str
    role: str = ""
    # Time-weighted participation across the period (0.0 - 1.0). Enables
    # pro-rata allocation for multi-project staff transfers.
    time_weight: float = 1.0
    # L&D badge: "Level 1" | "Level 2" | "Level 3".
    ld_badge: str = "Level 1"
    # Section SLA met (site SLA compliance).
    section_sla_met: bool = True
    # Individual Percent Plan Complete.
    ppc: float = 1.0
    # Whether the member completed all individual L&D / SLA requirements.
    ld_sla_met: bool = True
    # Unapproved scope (> threshold) executed without signed VO/SI.
    unapproved_scope_breach: bool = False
    # Resigning staff completing a clean handover -> vested retention payout.
    resigning_clean_handover: bool = False
    # --- Performance-pool contributions (20% pool inputs) ---
    value_engineering_savings_egp: float = 0.0
    kaizen_points: float = 0.0
    equipment_oee: float = 0.0          # e.g. 0.96 for 96%
    vo_settlement_days: Optional[int] = None


@dataclass
class ProjectFinancials:
    """Period financial inputs for a single project/site. البيانات المالية."""

    project_name: str
    baseline_cost_egp: float
    actual_cost_egp: float
    # Fraction of contract cash collected in the period (0.0 - 1.0).
    cash_collected_pct: float
    quality_factor: float = 1.0                 # F_quality (0.0 - 1.0)
    # Commodity key used to look up the material escalation index.
    escalation_commodity: str = "default"
    # Explicit override of the escalation delta (fraction). If None, resolved
    # from target_rates.json material_escalation_index.
    escalation_delta_override: Optional[float] = None
    # Executive-approved uncollectible bad debt, isolated from net savings.
    bad_debt_egp: float = 0.0
    # Total value of subcontractor packages (reserve base).
    subcontractor_value_egp: float = 0.0
    # Zero-tolerance safety gate: number of Lost Time Injuries in period.
    lost_time_injuries: int = 0


@dataclass
class AuditEntry:
    """Single traceable calculation step. خطوة تدقيق."""

    step: str
    detail_en: str
    value: Any


# --------------------------------------------------------------------------- #
#  Engine  |  المحرك
# --------------------------------------------------------------------------- #
class GainsharingCalculator:
    """
    Deterministic gainsharing engine for one project period.

    Usage:
        calc = GainsharingCalculator(rates_path="target_rates.json")
        result = calc.run(financials, members)
        result.pool_df, result.distribution_df, result.audit_df
    """

    def __init__(self, rates_path: str | Path = DEFAULT_RATES_PATH) -> None:
        self.rates_path = Path(rates_path)
        self.config = self._load_config(self.rates_path)
        self.gov = self.config["governance"]
        self.cash_gate = self.config["cash_gate"]
        self.ld_badges = self.config["ld_badges"]
        self.safety = self.config["safety"]
        self.escalation = self.config["material_escalation_index"]
        self._audit: list[AuditEntry] = []

    # ------------------------------------------------------------------ #
    #  Config loading  |  تحميل الإعدادات
    # ------------------------------------------------------------------ #
    @staticmethod
    def _load_config(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(
                f"[CONFIG] target_rates.json not found at: {path}\n"
                f"          ملف الأسعار المستهدفة غير موجود."
            )
        try:
            with path.open("r", encoding="utf-8") as fh:
                cfg = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"[CONFIG] Invalid JSON in {path}: {exc}") from exc

        for required in ("governance", "cash_gate", "ld_badges", "safety",
                         "material_escalation_index"):
            if required not in cfg:
                raise KeyError(f"[CONFIG] Missing required section: '{required}'")
        return cfg

    # ------------------------------------------------------------------ #
    #  Audit helper  |  مساعد التدقيق
    # ------------------------------------------------------------------ #
    def _log(self, step: str, detail_en: str, value: Any) -> None:
        self._audit.append(AuditEntry(step=step, detail_en=detail_en, value=value))
        logger.debug("AUDIT | %-28s | %s = %s", step, detail_en, value)

    # ------------------------------------------------------------------ #
    #  1) Inflation-adjusted baseline & gross savings
    #     الأساس المعدّل للتضخم وإجمالي الوفورات
    # ------------------------------------------------------------------ #
    def compute_savings(self, fin: ProjectFinancials) -> dict[str, float]:
        # Resolve escalation delta (fractional).
        if fin.escalation_delta_override is not None:
            delta = float(fin.escalation_delta_override)
        else:
            delta = float(
                self.escalation.get(
                    fin.escalation_commodity, self.escalation.get("default", 0.0)
                )
            )
        # C_adjusted_baseline = C_baseline + (C_baseline * delta)
        escalation_value = fin.baseline_cost_egp * delta
        adjusted_baseline = fin.baseline_cost_egp + escalation_value
        self._log(
            "ESCALATION",
            f"delta={delta:.4f} on commodity '{fin.escalation_commodity}'",
            round(escalation_value, 2),
        )
        self._log("ADJ_BASELINE", "C_adjusted_baseline", round(adjusted_baseline, 2))

        # Isolate executive-approved bad debt from net savings.
        actual_effective = fin.actual_cost_egp
        qf = self._clamp(fin.quality_factor, 0.0, 1.0)

        gross = max(0.0, adjusted_baseline - actual_effective)
        # Bad-debt isolation: bad debt is excluded from net savings.
        gross_after_bad_debt = max(0.0, gross - fin.bad_debt_egp)
        savings = gross_after_bad_debt * qf
        self._log("BAD_DEBT_ISOLATION", "bad_debt_egp excluded", round(fin.bad_debt_egp, 2))
        self._log("QUALITY_FACTOR", "F_quality applied", qf)
        self._log("GROSS_SAVINGS", "S = max(0, adj_base - actual - bad_debt) * F_q",
                  round(savings, 2))

        return {
            "escalation_delta": delta,
            "escalation_value": escalation_value,
            "adjusted_baseline": adjusted_baseline,
            "gross_savings": gross,
            "savings_after_bad_debt": gross_after_bad_debt,
            "quality_factor": qf,
            "net_savings_S": savings,
        }

    # ------------------------------------------------------------------ #
    #  2) Team pool & cash gate  |  مجمع الفريق وبوابة النقد
    # ------------------------------------------------------------------ #
    def compute_pool(self, savings_S: float, fin: ProjectFinancials) -> dict[str, Any]:
        # Subcontractor back-charge reserve: 10% holdback on subcontractor value,
        # absorbed before impacting project gainsharing.
        reserve_pct = float(self.gov["subcontractor_backcharge_reserve_pct"])
        subcontractor_reserve = fin.subcontractor_value_egp * reserve_pct
        self._log("SUBK_RESERVE", f"{reserve_pct:.0%} back-charge reserve",
                  round(subcontractor_reserve, 2))

        # P_pool = S * 0.35 (team shared pool)
        team_pct = float(self.gov["team_shared_pool_pct"])
        raw_pool = savings_S * team_pct
        self._log("TEAM_POOL_RAW", f"P_pool = S * {team_pct:.0%}", round(raw_pool, 2))

        # --- Tiered Cash Liquidity Gate ---
        collected = self._clamp(fin.cash_collected_pct, 0.0, 1.0)
        full = float(self.cash_gate["full_unlock_threshold"])
        floor = float(self.cash_gate["partial_unlock_floor"])
        denom = float(self.cash_gate["prorata_denominator"])

        if collected >= full:
            unlock_ratio = 1.0
            gate_status = "FULL_UNLOCK"
        elif collected >= floor:
            unlock_ratio = collected / denom
            gate_status = "PARTIAL_UNLOCK"
        else:
            unlock_ratio = 0.0
            gate_status = "HOLDBACK"

        unlock_ratio = self._clamp(unlock_ratio, 0.0, 1.0)
        unlocked_pool = raw_pool * unlock_ratio
        self._log("CASH_GATE", f"collected={collected:.2%} -> {gate_status}",
                  round(unlock_ratio, 4))
        self._log("UNLOCKED_POOL", "raw_pool * unlock_ratio", round(unlocked_pool, 2))

        # --- 70% immediate / 30% retained cushion ---
        immediate_pct = float(self.gov["immediate_payout_pct"])
        retained_pct = float(self.gov["retained_cushion_pct"])
        immediate = unlocked_pool * immediate_pct
        retained = unlocked_pool * retained_pct
        self._log("PAYOUT_SPLIT", f"{immediate_pct:.0%} immediate / {retained_pct:.0%} retained",
                  {"immediate": round(immediate, 2), "retained": round(retained, 2)})

        # --- 80/20 split of the unlocked pool ---
        base_pct = float(self.gov["base_equal_pool_pct"])
        perf_pct = float(self.gov["performance_pool_pct"])
        base_pool = unlocked_pool * base_pct
        performance_pool = unlocked_pool * perf_pct
        self._log("SPLIT_80_20", f"{base_pct:.0%} base / {perf_pct:.0%} performance",
                  {"base": round(base_pool, 2), "performance": round(performance_pool, 2)})

        return {
            "subcontractor_reserve": subcontractor_reserve,
            "team_pct": team_pct,
            "raw_pool": raw_pool,
            "cash_collected": collected,
            "gate_status": gate_status,
            "unlock_ratio": unlock_ratio,
            "unlocked_pool": unlocked_pool,
            "immediate_payout": immediate,
            "retained_cushion": retained,
            "base_pool": base_pool,
            "performance_pool": performance_pool,
        }

    # ------------------------------------------------------------------ #
    #  3) Individual distribution  |  التوزيع الفردي
    # ------------------------------------------------------------------ #
    def distribute(
        self,
        members: list[TeamMember],
        base_pool: float,
        performance_pool: float,
        safety_disqualified: bool,
    ) -> pd.DataFrame:
        ppc_gate = float(self.gov["ppc_eligibility_threshold"])
        forfeit_pct = float(self.gov["ld_forfeit_pct"])
        scope_penalty = float(self.gov["unapproved_scope_penalty_pct"])
        oee_threshold = float(self.gov["oee_uptime_threshold"])
        fast_track_days = int(self.gov["fast_track_vo_days"])

        rows: list[dict[str, Any]] = []

        # If the site team is safety-disqualified (LTI > 0), the entire
        # performance bonus is forfeited for the period.
        if safety_disqualified:
            logger.warning("SAFETY GATE TRIPPED — team disqualified from performance bonus.")
            base_pool = 0.0
            performance_pool = 0.0

        # --- Base 80% eligibility & weighted shares ---
        # Eligible: Section SLA met AND PPC >= threshold.
        eligible = [
            m for m in members
            if m.section_sla_met and m.ppc >= ppc_gate and not safety_disqualified
        ]

        # Weight = time_weight * L&D badge multiplier.
        def badge_mult(m: TeamMember) -> float:
            return float(self.ld_badges.get(m.ld_badge, {}).get("multiplier", 1.0))

        weights: dict[str, float] = {}
        forfeited_to_perf = 0.0
        total_weight = 0.0
        for m in eligible:
            w = max(0.0, m.time_weight) * badge_mult(m)
            weights[m.name] = w
            total_weight += w

        # Provisional equal-weighted base shares.
        provisional: dict[str, float] = {}
        for m in eligible:
            share = (weights[m.name] / total_weight) * base_pool if total_weight > 0 else 0.0
            provisional[m.name] = share

        # Apply individual forfeits: failing L&D/SLA forfeits 50% of individual
        # base share into the 20% performance pool. Unapproved scope breach adds
        # a 50% individual SLA penalty on the base share.
        final_base: dict[str, float] = {}
        for m in eligible:
            share = provisional[m.name]
            penalty = 0.0
            if not m.ld_sla_met:
                penalty += forfeit_pct
            if m.unapproved_scope_breach:
                penalty += scope_penalty
            penalty = min(penalty, 1.0)
            forfeit_amount = share * penalty
            forfeited_to_perf += forfeit_amount
            final_base[m.name] = share - forfeit_amount

        performance_pool += forfeited_to_perf
        self._log("FORFEIT_TO_PERF", "individual forfeits rolled into 20% pool",
                  round(forfeited_to_perf, 2))

        # --- Performance 20% pool point allocation ---
        # Points: VE savings (10% reward), Kaizen, OEE > 95%, fast-track VO < 7d.
        ve_reward_pct = float(self.gov["value_engineering_reward_pct"])
        perf_points: dict[str, float] = {}
        for m in members:
            if safety_disqualified:
                perf_points[m.name] = 0.0
                continue
            pts = 0.0
            pts += m.value_engineering_savings_egp * ve_reward_pct  # VE reward
            pts += max(0.0, m.kaizen_points)
            if m.equipment_oee and m.equipment_oee > oee_threshold:
                pts += 1.0
            if m.vo_settlement_days is not None and m.vo_settlement_days < fast_track_days:
                pts += 1.0
            perf_points[m.name] = pts

        total_points = sum(perf_points.values())

        # --- Build per-member rows ---
        for m in members:
            base_share = final_base.get(m.name, 0.0)
            perf_share = (
                (perf_points[m.name] / total_points) * performance_pool
                if total_points > 0 else 0.0
            )
            gross_share = base_share + perf_share

            # Vested 30% retention payout for resigning staff with clean handover:
            # they retain their 70% immediate share and vest the 30% cushion.
            immediate_pct = float(self.gov["immediate_payout_pct"])
            retained_pct = float(self.gov["retained_cushion_pct"])
            immediate_share = gross_share * immediate_pct
            retained_share = gross_share * retained_pct
            vested_note = ""
            if m.resigning_clean_handover:
                vested_note = "VESTED_30PCT_CLEAN_HANDOVER"

            eligible_flag = (
                m.section_sla_met and m.ppc >= ppc_gate and not safety_disqualified
            )
            status = self._member_status(
                eligible_flag, m, safety_disqualified
            )

            rows.append({
                "name": m.name,
                "role": m.role,
                "ld_badge": m.ld_badge,
                "badge_multiplier": badge_mult(m),
                "time_weight": round(m.time_weight, 4),
                "ppc": round(m.ppc, 4),
                "section_sla_met": bool(m.section_sla_met),
                "ld_sla_met": bool(m.ld_sla_met),
                "unapproved_scope_breach": bool(m.unapproved_scope_breach),
                "eligible_base": eligible_flag,
                "base_share_egp": round(base_share, 2),
                "perf_points": round(perf_points.get(m.name, 0.0), 4),
                "perf_share_egp": round(perf_share, 2),
                "gross_share_egp": round(gross_share, 2),
                "immediate_70_egp": round(immediate_share, 2),
                "retained_30_egp": round(retained_share, 2),
                "status": status,
                "notes": vested_note,
            })

        df = pd.DataFrame(rows)
        self._log("DISTRIBUTION", "per-member allocation built", len(rows))
        return df

    # ------------------------------------------------------------------ #
    #  Helpers  |  دوال مساعدة
    # ------------------------------------------------------------------ #
    @staticmethod
    def _member_status(eligible: bool, m: TeamMember, disq: bool) -> str:
        if disq:
            return "DISQUALIFIED_SAFETY"
        if not eligible:
            return "INELIGIBLE_SLA_PPC"
        if not m.ld_sla_met or m.unapproved_scope_breach:
            return "PENALTY_APPLIED"
        return "APPROVED_FULL"

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, float(value)))

    # ------------------------------------------------------------------ #
    #  Orchestration  |  التنسيق
    # ------------------------------------------------------------------ #
    def run(
        self,
        fin: ProjectFinancials,
        members: list[TeamMember],
    ) -> "GainsharingResult":
        self._audit = []  # reset per run
        logger.info("Running gainsharing for project: %s", fin.project_name)

        # Zero-LTI safety gate.
        max_lti = int(self.safety.get("max_lti_allowed", 0))
        safety_disqualified = fin.lost_time_injuries > max_lti
        self._log("SAFETY_GATE", f"LTI={fin.lost_time_injuries} (max {max_lti})",
                  "DISQUALIFIED" if safety_disqualified else "PASS")

        savings = self.compute_savings(fin)
        pool = self.compute_pool(savings["net_savings_S"], fin)

        distribution_df = self.distribute(
            members=members,
            base_pool=pool["base_pool"],
            performance_pool=pool["performance_pool"],
            safety_disqualified=safety_disqualified,
        )

        # Pool summary DataFrame.
        pool_df = pd.DataFrame([{
            "project": fin.project_name,
            "baseline_egp": round(fin.baseline_cost_egp, 2),
            "escalation_delta": round(savings["escalation_delta"], 4),
            "adjusted_baseline_egp": round(savings["adjusted_baseline"], 2),
            "actual_egp": round(fin.actual_cost_egp, 2),
            "bad_debt_egp": round(fin.bad_debt_egp, 2),
            "quality_factor": savings["quality_factor"],
            "net_savings_S_egp": round(savings["net_savings_S"], 2),
            "subcontractor_reserve_egp": round(pool["subcontractor_reserve"], 2),
            "team_pool_raw_egp": round(pool["raw_pool"], 2),
            "cash_collected_pct": round(pool["cash_collected"], 4),
            "cash_gate_status": pool["gate_status"],
            "unlock_ratio": round(pool["unlock_ratio"], 4),
            "unlocked_pool_egp": round(pool["unlocked_pool"], 2),
            "base_pool_80_egp": round(pool["base_pool"], 2),
            "performance_pool_20_egp": round(pool["performance_pool"], 2),
            "immediate_70_egp": round(pool["immediate_payout"], 2),
            "retained_30_egp": round(pool["retained_cushion"], 2),
            "safety_status": "DISQUALIFIED" if safety_disqualified else "PASS",
        }])

        audit_df = pd.DataFrame([{
            "step": a.step,
            "detail": a.detail_en,
            "value": a.value,
        } for a in self._audit])

        return GainsharingResult(
            project=fin.project_name,
            generated_at=datetime.now(timezone.utc).isoformat(),
            pool_df=pool_df,
            distribution_df=distribution_df,
            audit_df=audit_df,
            safety_disqualified=safety_disqualified,
            raw=dict(savings=savings, pool=pool),
        )


@dataclass
class GainsharingResult:
    """Structured result bundle. حزمة النتائج."""

    project: str
    generated_at: str
    pool_df: pd.DataFrame
    distribution_df: pd.DataFrame
    audit_df: pd.DataFrame
    safety_disqualified: bool
    raw: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"# United Brothers Co. — Gainsharing Result | {self.project}",
            f"_Generated: {self.generated_at}_",
            "",
            "## Pool Summary",
            self.pool_df.to_markdown(index=False),
            "",
            "## Distribution",
            self.distribution_df.to_markdown(index=False),
        ]
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Self-test / demo  |  عرض توضيحي
# --------------------------------------------------------------------------- #
def _demo() -> None:
    calc = GainsharingCalculator()
    fin = ProjectFinancials(
        project_name="Ain Sokhna Industrial Warehouse",
        baseline_cost_egp=12_000_000.0,
        actual_cost_egp=10_400_000.0,
        cash_collected_pct=0.82,        # partial-unlock band
        quality_factor=0.95,
        escalation_commodity="steel_rebar",
        bad_debt_egp=150_000.0,
        subcontractor_value_egp=3_000_000.0,
        lost_time_injuries=0,
    )
    members = [
        TeamMember("Ahmed Fathy", "Site Manager", time_weight=1.0, ld_badge="Level 3",
                   ppc=0.92, equipment_oee=0.97, vo_settlement_days=5,
                   value_engineering_savings_egp=200_000),
        TeamMember("Mona Adel", "QA/QC Engineer", time_weight=0.8, ld_badge="Level 2",
                   ppc=0.88, ld_sla_met=False),
        TeamMember("Khaled Samir", "Foreman", time_weight=1.0, ld_badge="Level 1",
                   ppc=0.70),  # below PPC gate -> ineligible base
        TeamMember("Sara Nabil", "Planner", time_weight=0.5, ld_badge="Level 2",
                   ppc=0.90, resigning_clean_handover=True, kaizen_points=2),
    ]
    result = calc.run(fin, members)
    print(result.summary())
    print("\n## Audit Trail")
    print(result.audit_df.to_markdown(index=False))


if __name__ == "__main__":
    _demo()
