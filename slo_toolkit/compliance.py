"""
SLO compliance reporting: calculate remaining error budget,
project end-of-window status, and generate human-readable summaries.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import List, Tuple
import datetime


@dataclass
class CompliancePeriod:
    """A single time period's worth of reliability data."""
    start: datetime.datetime
    end: datetime.datetime
    total_requests: int
    error_requests: int

    @property
    def error_rate(self) -> float:
        return self.error_requests / self.total_requests if self.total_requests > 0 else 0.0

    @property
    def duration_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


@dataclass
class SLOComplianceReport:
    """
    Compute and report on SLO compliance across a compliance window.

    Tracks error budget consumed, projects end-of-window status,
    and surfaces the highest-severity burn-rate period.
    """

    slo_target: float
    compliance_window_days: int
    periods: List[CompliancePeriod]

    def __post_init__(self) -> None:
        self._error_budget = 1.0 - self.slo_target

    # ── Core metrics ─────────────────────────────────────────────────────────

    @property
    def total_requests(self) -> int:
        return sum(p.total_requests for p in self.periods)

    @property
    def total_errors(self) -> int:
        return sum(p.error_requests for p in self.periods)

    @property
    def observed_error_rate(self) -> float:
        return self.total_errors / self.total_requests if self.total_requests > 0 else 0.0

    @property
    def error_budget_consumed_fraction(self) -> float:
        """Fraction of error budget consumed (0.0 = none, 1.0 = fully exhausted)."""
        return self.observed_error_rate / self._error_budget if self._error_budget > 0 else 1.0

    @property
    def error_budget_remaining_pct(self) -> float:
        return max(0.0, (1.0 - self.error_budget_consumed_fraction) * 100)

    @property
    def compliant(self) -> bool:
        return self.observed_error_rate <= self._error_budget

    # ── Projection ───────────────────────────────────────────────────────────

    def project_end_of_window(
        self,
        hours_elapsed: float,
    ) -> Tuple[float, bool]:
        """
        Project whether the SLO will be met at end of compliance window
        if current error rate continues.

        Args:
            hours_elapsed: Hours elapsed in the compliance window so far.

        Returns:
            (projected_error_rate, will_comply)
        """
        total_hours = self.compliance_window_days * 24
        # Assume current rate continues for remainder of window
        projected_rate = self.observed_error_rate  # simplified: rate is constant
        will_comply = projected_rate <= self._error_budget
        return projected_rate, will_comply

    # ── Reporting ─────────────────────────────────────────────────────────────

    def summary(self) -> str:
        status = "✅ COMPLIANT" if self.compliant else "❌ BREACHED"
        lines = [
            f"SLO Compliance Report",
            f"{'─' * 40}",
            f"SLO Target:            {self.slo_target * 100:.3f}%",
            f"Window:                {self.compliance_window_days} days",
            f"Status:                {status}",
            f"",
            f"Observed error rate:   {self.observed_error_rate * 100:.4f}%",
            f"Error budget:          {self._error_budget * 100:.4f}%",
            f"Budget consumed:       {self.error_budget_consumed_fraction * 100:.1f}%",
            f"Budget remaining:      {self.error_budget_remaining_pct:.1f}%",
            f"",
            f"Total requests:        {self.total_requests:,}",
            f"Total errors:          {self.total_errors:,}",
        ]
        if self.periods:
            lines += [
                f"",
                f"Periods analyzed:      {len(self.periods)}",
                f"From:                  {self.periods[0].start.strftime('%Y-%m-%d %H:%M')}",
                f"To:                    {self.periods[-1].end.strftime('%Y-%m-%d %H:%M')}",
            ]
        return "\n".join(lines)

    @classmethod
    def from_prometheus_samples(
        cls,
        slo_target: float,
        compliance_window_days: int,
        samples: List[dict],
    ) -> "SLOComplianceReport":
        """
        Build a report from Prometheus instant query samples.

        Each sample should be:
          {"timestamp": datetime, "total": int, "errors": int}
        """
        periods = []
        for i, s in enumerate(samples):
            if i == 0:
                continue
            prev = samples[i - 1]
            periods.append(CompliancePeriod(
                start=prev["timestamp"],
                end=s["timestamp"],
                total_requests=s["total"] - prev["total"],
                error_requests=s["errors"] - prev["errors"],
            ))
        return cls(
            slo_target=slo_target,
            compliance_window_days=compliance_window_days,
            periods=periods,
        )
