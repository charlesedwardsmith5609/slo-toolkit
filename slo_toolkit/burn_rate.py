"""
Burn rate calculation for SLO error budget management.

A burn rate tells you how fast you are consuming your error budget relative
to the allowed rate. A burn rate of 1x means you are consuming exactly at the
rate that would exhaust your budget at the end of the compliance window.
A burn rate of 2x means you'll exhaust it in half the time.

Multi-window burn rate alerting (Google SRE Workbook, Alerting on SLOs):
  - Fast burn (2% budget in 1h)  → page immediately
  - Slow burn (5% budget in 6h)  → page, less urgent
  - Very slow (10% budget in 3d) → ticket
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Union

from .types import BurnRateStatus, SLIType


@dataclass
class BurnRateResult:
    """Result of a burn rate calculation."""

    error_rate: float  # Observed error rate (0.0–1.0)
    slo_target: float  # SLO target (e.g. 0.999 = 99.9%)
    error_budget: float  # Allowed error budget for the SLO (1 - target)
    burn_rate: float  # Current burn rate (1.0 = sustainable)
    time_to_exhaustion_hours: Optional[float]  # Hours until budget exhausted
    compliance_window_hours: float  # SLO compliance window
    # Remaining % of caller-supplied cumulative budget (1 - budget_consumed_fraction).
    # Default calculate() passes consumed=0 → this shows 100%, not "month left."
    budget_remaining_pct: float
    status: BurnRateStatus
    sli_type: SLIType = SLIType.AVAILABILITY
    bad_events: Optional[int] = None
    total_events: Optional[int] = None

    def __str__(self) -> str:
        tte = (
            f"{self.time_to_exhaustion_hours:.1f}h"
            if self.time_to_exhaustion_hours is not None
            else "∞"
        )
        return (
            f"Burn Rate: {self.burn_rate:.2f}x  |  "
            f"Budget remaining: {self.budget_remaining_pct:.1f}%  |  "
            f"Time to exhaustion: {tte}  |  "
            f"Status: {self.status.value}"
        )


class BurnRateCalculator:
    """
    Calculate SLO burn rate and error budget consumption.

    Args:
        slo_target:             SLO target as a decimal (e.g. 0.999 for 99.9%)
        compliance_window_days: Length of the SLO compliance window in days
        sli_type:               SLI shape (availability / latency / freshness)
    """

    def __init__(
        self,
        slo_target: float = 0.999,
        compliance_window_days: int = 30,
        sli_type: Union[SLIType, str] = SLIType.AVAILABILITY,
    ) -> None:
        if not 0 < slo_target < 1:
            raise ValueError("slo_target must be between 0 and 1 exclusive")
        if compliance_window_days <= 0:
            raise ValueError("compliance_window_days must be positive")
        self.slo_target = slo_target
        self.compliance_window_days = compliance_window_days
        self.compliance_window_hours = compliance_window_days * 24
        self.sli_type = SLIType(sli_type)
        # Allowed error budget = 1 - SLO target.
        # Round to cancel binary float noise (e.g. 1.0 - 0.999 → 0.0010000000000000009),
        # which otherwise makes a 1x burn rate compare as slightly under 1.0.
        self.error_budget = round(1.0 - slo_target, 12)
        # Status thresholds scale with the compliance window (same formulas as
        # multi-window alerts: 2% budget in 1h → CRITICAL, 5% in 6h → WARNING).
        self.critical_burn_rate = self.burn_rate_for_alert_threshold(0.02, 1)
        self.warning_burn_rate = self.burn_rate_for_alert_threshold(0.05, 6)

    def calculate(
        self,
        error_rate: float,
        budget_consumed_fraction: float = 0.0,
        *,
        bad_events: Optional[int] = None,
        total_events: Optional[int] = None,
    ) -> BurnRateResult:
        """
        Calculate current burn rate given an observed error rate.

        Args:
            error_rate:                Observed error rate (0.0–1.0).
            budget_consumed_fraction:  Cumulative fraction of the *full-window*
                                       error allowance already spent (0.0–1.0).
                                       Distinct from burn rate (instantaneous pace).
            bad_events / total_events: Optional counts echoed on the result.

        Returns:
            BurnRateResult with burn rate, status, and time-to-exhaustion.
        """
        if error_rate < 0 or error_rate > 1:
            raise ValueError("error_rate must be between 0 and 1")
        if budget_consumed_fraction < 0 or budget_consumed_fraction > 1:
            raise ValueError("budget_consumed_fraction must be between 0 and 1")

        burn_rate = (
            error_rate / self.error_budget if self.error_budget > 0 else float("inf")
        )

        budget_remaining = 1.0 - budget_consumed_fraction
        budget_remaining_pct = budget_remaining * 100

        if burn_rate > 0 and budget_remaining > 0:
            hours_for_full_budget = self.compliance_window_hours / burn_rate
            time_to_exhaustion = hours_for_full_budget * budget_remaining
        elif burn_rate == 0:
            time_to_exhaustion = None
        else:
            time_to_exhaustion = 0.0

        if budget_remaining <= 0:
            status = BurnRateStatus.EXHAUSTED
        elif burn_rate >= self.critical_burn_rate:
            status = BurnRateStatus.CRITICAL
        elif burn_rate >= self.warning_burn_rate:
            status = BurnRateStatus.WARNING
        elif burn_rate >= 1.0:
            status = BurnRateStatus.ELEVATED
        else:
            status = BurnRateStatus.OK

        return BurnRateResult(
            error_rate=error_rate,
            slo_target=self.slo_target,
            error_budget=self.error_budget,
            burn_rate=burn_rate,
            time_to_exhaustion_hours=time_to_exhaustion,
            compliance_window_hours=self.compliance_window_hours,
            budget_remaining_pct=budget_remaining_pct,
            status=status,
            sli_type=self.sli_type,
            bad_events=bad_events,
            total_events=total_events,
        )

    def calculate_from_counts(
        self,
        bad_events: int,
        total_events: int,
        budget_consumed_fraction: float = 0.0,
    ) -> BurnRateResult:
        """
        Burn rate from good/bad event counts (preferred for low-traffic windows).

        error_rate = bad_events / total_events when total_events > 0, else 0.
        """
        if bad_events < 0 or total_events < 0:
            raise ValueError("event counts must be non-negative")
        if bad_events > total_events:
            raise ValueError("bad_events cannot exceed total_events")
        error_rate = bad_events / total_events if total_events > 0 else 0.0
        return self.calculate(
            error_rate=error_rate,
            budget_consumed_fraction=budget_consumed_fraction,
            bad_events=bad_events,
            total_events=total_events,
        )

    def burn_rate_for_alert_threshold(
        self,
        budget_fraction: float,
        window_hours: float,
    ) -> float:
        """
        Burn rate that would consume `budget_fraction` of the error budget
        within `window_hours`:

          burn_rate = (budget_fraction * compliance_window) / window_hours
        """
        if window_hours <= 0:
            raise ValueError("window_hours must be positive")
        if budget_fraction < 0:
            raise ValueError("budget_fraction must be non-negative")
        return (budget_fraction * self.compliance_window_hours) / window_hours
