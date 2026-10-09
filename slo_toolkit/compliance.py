"""
SLO compliance reporting: calculate remaining error budget,
project end-of-window status, and generate human-readable summaries.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from typing import List, Optional, Tuple, Union

from .burn_rate import BurnRateCalculator, BurnRateResult
from .types import BurnRateStatus, ProjectionMode, SLIType


@dataclass
class CompliancePeriod:
    """A single time period's worth of reliability data."""

    start: datetime.datetime
    end: datetime.datetime
    total_requests: int
    error_requests: int

    def __post_init__(self) -> None:
        if self.total_requests < 0:
            raise ValueError("total_requests must be non-negative")
        if self.error_requests < 0:
            raise ValueError("error_requests must be non-negative")
        if self.error_requests > self.total_requests:
            raise ValueError("error_requests cannot exceed total_requests")
        if self.end < self.start:
            raise ValueError("end must be >= start")
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must be timezone-aware")

    @property
    def error_rate(self) -> float:
        return (
            self.error_requests / self.total_requests
            if self.total_requests > 0
            else 0.0
        )

    @property
    def duration_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


@dataclass
class WindowProjection:
    """Result of an end-of-window projection."""

    mode: ProjectionMode
    projected_error_rate: float
    will_comply: bool
    projected_budget_consumed_fraction: float
    hours_elapsed: float


@dataclass
class SLOComplianceReport:
    """
    Compute and report on SLO compliance across a compliance window.

    Distinguishes:
      - rate_budget_ratio: observed_error_rate / error_budget (pace vs allowance)
      - cumulative_budget_consumed_fraction: absolute allowance used so far,
        assuming constant request volume through the window
    """

    slo_target: float
    compliance_window_days: int
    periods: List[CompliancePeriod]
    sli_type: Union[SLIType, str] = SLIType.AVAILABILITY

    def __post_init__(self) -> None:
        if not 0 < self.slo_target < 1:
            raise ValueError("slo_target must be between 0 and 1 exclusive")
        if self.compliance_window_days <= 0:
            raise ValueError("compliance_window_days must be positive")
        self.sli_type = SLIType(self.sli_type)
        self._error_budget = round(1.0 - self.slo_target, 12)
        self._calculator = BurnRateCalculator(
            slo_target=self.slo_target,
            compliance_window_days=self.compliance_window_days,
            sli_type=self.sli_type,
        )

    @property
    def total_requests(self) -> int:
        return sum(p.total_requests for p in self.periods)

    @property
    def total_errors(self) -> int:
        return sum(p.error_requests for p in self.periods)

    @property
    def observed_error_rate(self) -> float:
        return (
            self.total_errors / self.total_requests if self.total_requests > 0 else 0.0
        )

    @property
    def rate_budget_ratio(self) -> float:
        """
        How the observed error *rate* compares to the allowed budget rate.

        1.0 means burning exactly at the sustainable rate. This is NOT
        calendar progress through the window.
        """
        if self._error_budget <= 0:
            return 1.0
        return self.observed_error_rate / self._error_budget

    @property
    def error_budget_consumed_fraction(self) -> float:
        """
        Alias for rate_budget_ratio (kept for API compatibility).

        Prefer rate_budget_ratio or cumulative_budget_consumed_fraction
        depending on whether you mean pace or absolute allowance used.
        """
        return self.rate_budget_ratio

    def cumulative_budget_consumed_fraction(self, hours_elapsed: float) -> float:
        """
        Fraction of the *full-window* error allowance already spent.

        Assumes constant RPS: expected full-window volume =
        total_requests * (window_hours / hours_elapsed). Allowed errors for
        that volume = error_budget * expected_volume. Cumulative consumed =
        total_errors / allowed_errors = rate_budget_ratio * (elapsed / window).
        """
        if hours_elapsed < 0:
            raise ValueError("hours_elapsed must be non-negative")
        total_hours = float(self.compliance_window_days * 24)
        if hours_elapsed == 0 or self.total_requests == 0:
            return 0.0
        elapsed = min(hours_elapsed, total_hours)
        return self.rate_budget_ratio * (elapsed / total_hours)

    @property
    def error_budget_remaining_pct(self) -> float:
        """Remaining % based on rate_budget_ratio (pace), clamped at 0."""
        return max(0.0, (1.0 - self.rate_budget_ratio) * 100)

    def cumulative_budget_remaining_pct(self, hours_elapsed: float) -> float:
        return max(
            0.0, (1.0 - self.cumulative_budget_consumed_fraction(hours_elapsed)) * 100
        )

    @property
    def compliant(self) -> bool:
        return self.observed_error_rate <= self._error_budget

    def project_end_of_window(
        self,
        hours_elapsed: float,
        mode: Union[ProjectionMode, str] = ProjectionMode.CONSTANT_RATE,
    ) -> WindowProjection:
        """
        Project end-of-window error rate and compliance.

        Modes:
          constant_rate — request-based SLIs: if the observed error rate
            continues, EOW rate equals the observed rate (hours_elapsed is
            unused for the rate itself; still validated).
          time_pace — calendar heuristic: scale rate_budget_ratio by
            window/elapsed. Prefer constant_rate for checkout-style SLIs.
        """
        if hours_elapsed < 0:
            raise ValueError("hours_elapsed must be non-negative")
        mode = ProjectionMode(mode)
        total_hours = float(self.compliance_window_days * 24)

        if self.total_requests == 0:
            return WindowProjection(
                mode=mode,
                projected_error_rate=0.0,
                will_comply=True,
                projected_budget_consumed_fraction=0.0,
                hours_elapsed=hours_elapsed,
            )

        if mode is ProjectionMode.CONSTANT_RATE:
            projected_rate = self.observed_error_rate
            projected_consumed = self.rate_budget_ratio
            will_comply = projected_rate <= self._error_budget
            return WindowProjection(
                mode=mode,
                projected_error_rate=projected_rate,
                will_comply=will_comply,
                projected_budget_consumed_fraction=projected_consumed,
                hours_elapsed=hours_elapsed,
            )

        # TIME_PACE
        if hours_elapsed >= total_hours:
            projected_rate = self.observed_error_rate
            projected_consumed = self.rate_budget_ratio
        elif hours_elapsed == 0:
            projected_rate = self.observed_error_rate
            projected_consumed = self.rate_budget_ratio
        else:
            projected_consumed = self.rate_budget_ratio * (total_hours / hours_elapsed)
            projected_rate = projected_consumed * self._error_budget

        return WindowProjection(
            mode=mode,
            projected_error_rate=projected_rate,
            will_comply=projected_consumed <= 1.0,
            projected_budget_consumed_fraction=projected_consumed,
            hours_elapsed=hours_elapsed,
        )

    def period_burn_rates(self) -> List[Tuple[CompliancePeriod, BurnRateResult]]:
        """Burn rate for each period (for hotspot analysis)."""
        results = []
        for period in self.periods:
            result = self._calculator.calculate_from_counts(
                bad_events=period.error_requests,
                total_events=period.total_requests,
            )
            results.append((period, result))
        return results

    def highest_severity_period(
        self,
    ) -> Optional[Tuple[CompliancePeriod, BurnRateResult]]:
        """Period with the worst burn-rate status, then highest burn_rate."""
        order = {
            BurnRateStatus.EXHAUSTED: 5,
            BurnRateStatus.CRITICAL: 4,
            BurnRateStatus.WARNING: 3,
            BurnRateStatus.ELEVATED: 2,
            BurnRateStatus.OK: 1,
        }
        ranked = self.period_burn_rates()
        if not ranked:
            return None
        return max(
            ranked,
            key=lambda item: (order[item[1].status], item[1].burn_rate),
        )

    def summary(self) -> str:
        status = "COMPLIANT" if self.compliant else "BREACHED"
        lines = [
            "SLO Compliance Report",
            f"{'─' * 40}",
            f"SLI type:              {self.sli_type.value}",
            f"SLO Target:            {self.slo_target * 100:.3f}%",
            f"Window:                {self.compliance_window_days} days",
            f"Status:                {status}",
            "",
            f"Observed error rate:   {self.observed_error_rate * 100:.4f}%",
            f"Error budget:          {self._error_budget * 100:.4f}%",
            f"Rate / budget:         {self.rate_budget_ratio * 100:.1f}%",
            f"Rate-budget remaining: {self.error_budget_remaining_pct:.1f}%",
            "",
            f"Total requests:        {self.total_requests:,}",
            f"Total errors:          {self.total_errors:,}",
        ]
        hotspot = self.highest_severity_period()
        if hotspot:
            period, br = hotspot
            lines += [
                "",
                f"Hottest period:        {period.start.isoformat()} → {period.end.isoformat()}",
                f"  burn_rate={br.burn_rate:.2f}x status={br.status.value}",
            ]
        if self.periods:
            lines += [
                "",
                f"Periods analyzed:      {len(self.periods)}",
                f"From:                  {self.periods[0].start.strftime('%Y-%m-%d %H:%M %Z')}",
                f"To:                    {self.periods[-1].end.strftime('%Y-%m-%d %H:%M %Z')}",
            ]
        return "\n".join(lines)

    @classmethod
    def from_prometheus_samples(
        cls,
        slo_target: float,
        compliance_window_days: int,
        samples: List[dict],
        sli_type: Union[SLIType, str] = SLIType.AVAILABILITY,
    ) -> "SLOComplianceReport":
        """
        Build a report from cumulative counter samples.

        Each sample: {"timestamp": datetime (tz-aware), "total": int, "errors": int}
        Deltas between consecutive samples must be non-negative (counters).
        """
        if len(samples) < 2:
            raise ValueError("need at least two samples to form a period")

        periods = []
        for i, s in enumerate(samples):
            if i == 0:
                continue
            prev = samples[i - 1]
            for key in ("timestamp", "total", "errors"):
                if key not in s or key not in prev:
                    raise ValueError(f"sample missing required key: {key}")

            total_delta = s["total"] - prev["total"]
            error_delta = s["errors"] - prev["errors"]
            if total_delta < 0 or error_delta < 0:
                raise ValueError(
                    "negative counter delta between samples "
                    f"(total={total_delta}, errors={error_delta}); "
                    "counters must be monotonic"
                )
            periods.append(
                CompliancePeriod(
                    start=prev["timestamp"],
                    end=s["timestamp"],
                    total_requests=total_delta,
                    error_requests=error_delta,
                )
            )
        return cls(
            slo_target=slo_target,
            compliance_window_days=compliance_window_days,
            periods=periods,
            sli_type=sli_type,
        )
