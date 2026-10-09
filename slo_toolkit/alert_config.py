"""
Generate multi-window burn rate alert configurations.

Implements the Google SRE Book Chapter 5 multi-window alerting strategy:
  - Short window catches fast-burning incidents quickly
  - Long window guards against false positives from short spikes
  - Both windows must trigger simultaneously for an alert to fire

Outputs configuration for Prometheus, Datadog, and generic JSON.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
import json

from .burn_rate import BurnRateCalculator


@dataclass
class AlertWindow:
    """A single burn rate alert window."""
    name: str
    short_window_hours: float
    long_window_hours: float
    budget_fraction: float         # Fraction of budget consumed to trigger
    burn_rate: float               # Derived burn rate threshold
    severity: str                  # page / ticket / info
    description: str


@dataclass
class AlertConfig:
    """Complete multi-window alert configuration for an SLO."""
    service: str
    slo_name: str
    slo_target: float
    compliance_window_days: int
    windows: List[AlertWindow] = field(default_factory=list)

    @property
    def error_budget(self) -> float:
        return round(1.0 - self.slo_target, 12)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON for storage or API submission."""
        return json.dumps({
            "service": self.service,
            "slo_name": self.slo_name,
            "slo_target": self.slo_target,
            "compliance_window_days": self.compliance_window_days,
            "alert_windows": [
                {
                    "name": w.name,
                    "short_window_hours": w.short_window_hours,
                    "long_window_hours": w.long_window_hours,
                    "budget_fraction_consumed": w.budget_fraction,
                    "burn_rate_threshold": round(w.burn_rate, 2),
                    "severity": w.severity,
                    "description": w.description,
                }
                for w in self.windows
            ],
        }, indent=indent)

    def to_prometheus_rules(self, metric_name: str = "request_errors_total") -> str:
        """
        Emit Prometheus alerting rules (YAML) for this SLO.
        Assumes a metric `{metric_name}` with labels `{status="error"}`.
        """
        lines = [
            "groups:",
            f"  - name: slo.{self.service}.{self.slo_name}",
            "    rules:",
        ]
        # Use str.format with doubled braces so Prometheus label selectors
        # like {status="error"} are not treated as format fields.
        error_rate_template = (
            'rate({metric}{{status="error"}}[{window}]) / '
            'rate({metric}[{window}])'
        )
        budget = self.error_budget
        for w in self.windows:
            short_expr = error_rate_template.format(
                metric=metric_name, window=f"{int(w.short_window_hours)}h"
            )
            long_expr = error_rate_template.format(
                metric=metric_name, window=f"{int(w.long_window_hours)}h"
            )
            lines += [
                f"      - alert: SLO{w.name.replace(' ', '')}BurnRate",
                f"        expr: >",
                f"          ({short_expr} / {budget}) > {w.burn_rate:.2f}",
                f"          and",
                f"          ({long_expr} / {budget}) > {w.burn_rate:.2f}",
                f"        labels:",
                f"          severity: {w.severity}",
                f"          service: {self.service}",
                f"          slo: {self.slo_name}",
                f"        annotations:",
                f"          summary: '{w.description}'",
                f"          runbook: 'https://runbooks.internal/{self.service}/slo'",
            ]
        return "\n".join(lines)

    def to_datadog_monitors(self) -> str:
        """
        Emit Datadog monitor definitions as JSON (one per window).

        Each monitor requires BOTH the short and long windows to exceed the
        burn-rate-derived error-rate threshold (same dual-window intent as
        the Prometheus rules).
        """
        monitors = []
        for w in self.windows:
            error_rate_threshold = self.error_budget * w.burn_rate
            short_h = int(w.short_window_hours)
            long_h = int(w.long_window_hours)
            short_q = (
                f"sum(last_{short_h}h):sum:requests.errors{{}}.as_count() / "
                f"sum(last_{short_h}h):sum:requests.total{{}}.as_count()"
            )
            long_q = (
                f"sum(last_{long_h}h):sum:requests.errors{{}}.as_count() / "
                f"sum(last_{long_h}h):sum:requests.total{{}}.as_count()"
            )
            monitors.append({
                "name": f"[SLO] {self.service} — {w.name}",
                "type": "query alert",
                "query": (
                    f"({short_q}) > {error_rate_threshold:.6f} "
                    f"and ({long_q}) > {error_rate_threshold:.6f}"
                ),
                "message": f"{w.description} @pagerduty-{w.severity}",
                "tags": [
                    f"service:{self.service}",
                    f"slo:{self.slo_name}",
                    f"severity:{w.severity}",
                ],
                "priority": 1 if w.severity == "page" else 3,
                "options": {
                    "thresholds": {"critical": error_rate_threshold},
                    "short_window_hours": short_h,
                    "long_window_hours": long_h,
                },
            })
        return json.dumps(monitors, indent=2)


class AlertConfigGenerator:
    """
    Generate multi-window burn rate alert configurations for an SLO.

    Args:
        calculator: A configured BurnRateCalculator instance.
    """

    # Google SRE Book recommended multi-window thresholds for 30-day windows
    DEFAULT_WINDOWS = [
        # (name, budget_pct, short_hours, long_hours, severity)
        ("Critical Fast Burn",  2,  1,   5,  "page"),
        ("High Slow Burn",      5,  6,  30,  "page"),
        ("Medium Burn",        10, 24,  72,  "ticket"),
        ("Low Burn",           10, 72, 168,  "info"),
    ]

    def __init__(self, calculator: BurnRateCalculator) -> None:
        self.calculator = calculator

    def generate(
        self,
        service: str,
        slo_name: str,
        custom_windows: Optional[list] = None,
    ) -> AlertConfig:
        """
        Generate a complete AlertConfig for the given service/SLO.

        Args:
            service:        Service name (used in alert labels)
            slo_name:       Human-readable SLO name
            custom_windows: Optional list of (name, budget_pct, short_h, long_h, severity)
                            tuples to override defaults.

        Returns:
            AlertConfig with all windows populated.
        """
        windows_spec = custom_windows or self.DEFAULT_WINDOWS
        windows = []

        for name, budget_pct, short_h, long_h, severity in windows_spec:
            budget_fraction = budget_pct / 100.0
            burn_rate = self.calculator.burn_rate_for_alert_threshold(
                budget_fraction=budget_fraction,
                window_hours=short_h,
            )
            windows.append(AlertWindow(
                name=name,
                short_window_hours=short_h,
                long_window_hours=long_h,
                budget_fraction=budget_fraction,
                burn_rate=burn_rate,
                severity=severity,
                description=(
                    f"{service} SLO '{slo_name}' is burning {budget_pct}% of its "
                    f"{self.calculator.compliance_window_hours // 24:.0f}d error budget "
                    f"in {short_h}h (burn rate ≥{burn_rate:.1f}x)"
                ),
            ))

        return AlertConfig(
            service=service,
            slo_name=slo_name,
            slo_target=self.calculator.slo_target,
            compliance_window_days=int(self.calculator.compliance_window_hours // 24),
            windows=windows,
        )
