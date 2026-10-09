"""Tests for Prometheus and Datadog alert rule generation."""
import json

import pytest

from slo_toolkit.alert_config import AlertConfigGenerator
from slo_toolkit.burn_rate import BurnRateCalculator


def test_to_prometheus_rules_emits_status_label_and_windows():
    """Label selectors must survive formatting; previously KeyError on status=."""
    calc = BurnRateCalculator(slo_target=0.999, compliance_window_days=30)
    config = AlertConfigGenerator(calc).generate(
        service="payments", slo_name="availability"
    )

    rules = config.to_prometheus_rules(metric_name="http_requests_total")

    assert '{status="error"}' in rules
    assert "rate(http_requests_total{status=\"error\"}[1h])" in rules
    assert "rate(http_requests_total[1h])" in rules
    assert "rate(http_requests_total{status=\"error\"}[5h])" in rules
    assert "rate(http_requests_total[5h])" in rules
    assert "{window}" not in rules


def test_default_critical_fast_burn_is_14_4x_for_30d():
    calc = BurnRateCalculator(slo_target=0.999, compliance_window_days=30)
    config = AlertConfigGenerator(calc).generate(
        service="payments", slo_name="availability"
    )
    critical = next(w for w in config.windows if w.name == "Critical Fast Burn")
    assert pytest.approx(critical.burn_rate, rel=1e-3) == 14.4
    assert critical.short_window_hours == 1
    assert critical.long_window_hours == 5


def test_datadog_monitors_require_both_windows():
    calc = BurnRateCalculator(slo_target=0.999, compliance_window_days=30)
    config = AlertConfigGenerator(calc).generate(
        service="payments", slo_name="availability"
    )
    monitors = json.loads(config.to_datadog_monitors())
    assert len(monitors) == 4

    critical = monitors[0]
    query = critical["query"]
    assert "last_1h" in query
    assert "last_5h" in query
    assert " and " in query
    assert critical["options"]["short_window_hours"] == 1
    assert critical["options"]["long_window_hours"] == 5
