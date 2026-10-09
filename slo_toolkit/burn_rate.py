"""
Burn rate calculation for SLO error budget management.

A burn rate tells you how fast you are consuming your error budget relative
to the allowed rate. A burn rate of 1x means you are consuming exactly at the
rate that would exhaust your budget at the end of the compliance window.
A burn rate of 2x means you'll exhaust it in half the time.

Multi-window burn rate alerting (Google SRE Book, Chapter 5):
  - Fast burn (2% budget in 1h)  → page immediately
  - Slow burn (5% budget in 6h)  → page, less urgent
  - Very slow (10% budget in 3d) → ticket
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional


@dataclass
class BurnRateResult:
    """Result of a burn rate calculation."""
    error_rate: float          # Observed error rate (0.0–1.0)
    slo_target: float          # SLO target (e.g. 0.999 = 99.9%)
    error_budget: float        # Remaining error budget (0.0–1.0)
    burn_rate: float           # Current burn rate (1.0 = sustainable)
    time_to_exhaustion_hours: Optional[float]  # Hours until budget exhausted
    compliance_window_hours: float             # SLO compliance window
    budget_remaining_pct: float               # % of budget remaining
    status: str                               # OK / WARNING / CRITICAL / EXHAUSTED

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
            f"Status: {self.status}"
        )


class BurnRateCalculator:
    """
    Calculate SLO burn rate and error budget consumption.

    Args:
        slo_target:             SLO target as a decimal (e.g. 0.999 for 99.9%)
        compliance_window_days: Length of the SLO compliance window in days
    """

    def __init__(
        self,
        slo_target: float = 0.999,
        compliance_window_days: int = 30,
    ) -> None:
        if not 0 < slo_target < 1:
            raise ValueError("slo_target must be between 0 and 1 exclusive")
        self.slo_target = slo_target
        self.compliance_window_hours = compliance_window_days * 24
        # Allowed error budget = 1 - SLO target.
        # Round to cancel binary float noise (e.g. 1.0 - 0.999 → 0.0010000000000000009),
        # which otherwise makes a 1x burn rate compare as slightly under 1.0.
        self.error_budget = round(1.0 - slo_target, 12)

    def calculate(
        self,
        error_rate: float,
        budget_consumed_fraction: float = 0.0,
    ) -> BurnRateResult:
        """
        Calculate current burn rate given an observed error rate.

        Args:
            error_rate:                Observed error rate (0.0–1.0).
                                       e.g. 0.005 means 0.5% of requests errored.
            budget_consumed_fraction:  How much of the error budget has already
                                       been consumed (0.0–1.0). Useful for
                                       intra-window calculations.

        Returns:
            BurnRateResult with burn rate, status, and time-to-exhaustion.
        """
        if error_rate < 0 or error_rate > 1:
            raise ValueError("error_rate must be between 0 and 1")
        if budget_consumed_fraction < 0 or budget_consumed_fraction > 1:
            raise ValueError("budget_consumed_fraction must be between 0 and 1")

        # Burn rate = how fast we're consuming budget relative to allowed rate
        # If error_rate == error_budget, burn rate == 1 (exactly sustainable)
        burn_rate = error_rate / self.error_budget if self.error_budget > 0 else float("inf")

        # Remaining budget
        budget_remaining = 1.0 - budget_consumed_fraction
        budget_remaining_pct = budget_remaining * 100

        # Time until budget is exhausted at current burn rate
        if burn_rate > 0 and budget_remaining > 0:
            # At burn_rate x, we exhaust the full window's budget in:
            # compliance_window / burn_rate
            # but we only have budget_remaining fraction left
            hours_for_full_budget = self.compliance_window_hours / burn_rate
            time_to_exhaustion = hours_for_full_budget * budget_remaining
        elif burn_rate == 0:
            time_to_exhaustion = None  # Never exhausted
        else:
            time_to_exhaustion = 0.0

        # Status thresholds (Google SRE multi-window defaults)
        if budget_remaining <= 0:
            status = "EXHAUSTED"
        elif burn_rate >= 14.4:   # Exhausts 2% of 30d budget in 1h
            status = "CRITICAL"
        elif burn_rate >= 6.0:    # Exhausts 5% of 30d budget in 6h
            status = "WARNING"
        elif burn_rate >= 1.0:    # Burning faster than sustainable
            status = "ELEVATED"
        else:
            status = "OK"

        return BurnRateResult(
            error_rate=error_rate,
            slo_target=self.slo_target,
            error_budget=self.error_budget,
            burn_rate=burn_rate,
            time_to_exhaustion_hours=time_to_exhaustion,
            compliance_window_hours=self.compliance_window_hours,
            budget_remaining_pct=budget_remaining_pct,
            status=status,
        )

    def burn_rate_for_alert_threshold(
        self,
        budget_fraction: float,
        window_hours: float,
    ) -> float:
        """
        Calculate the burn rate that would consume `budget_fraction` of the
        error budget within `window_hours`.

        Useful for deriving alert thresholds:
          burn_rate = (budget_fraction * compliance_window) / window_hours

        Args:
            budget_fraction: Fraction of budget to consume (e.g. 0.02 = 2%)
            window_hours:    Detection window in hours

        Returns:
            Burn rate threshold as a float.
        """
        return (budget_fraction * self.compliance_window_hours) / window_hours
