"""Tests for Prometheus and Datadog alert rule generation."""
import json
from pathlib import Path

import pytest

from slo_toolkit.alert_config import AlertConfigGenerator, MetricContract
from slo_toolkit.burn_rate import BurnRateCalculator
from slo_toolkit.types import ALERT_CONFIG_SCHEMA_VERSION, SLIType

GOLDEN_DIR = Path(__file__).parent / "golden"


def _config_30d():
    calc = BurnRateCalculator(
        slo_target=0.999,
        compliance_window_days=30,
        sli_type=SLIType.AVAILABILITY,
    )
    return AlertConfigGenerator(calc).generate(
        service="checkout",
        slo_name="availability",
        environment="production",
        metric_contract=MetricContract(
            prometheus_metric="http_requests_total",
            environment="production",
        ),
    )


def test_schema_version_in_json():
    data = json.loads(_config_30d().to_json())
    assert data["schema_version"] == ALERT_CONFIG_SCHEMA_VERSION
    assert data["environment"] == "production"
    assert data["sli_type"] == "availability"
    assert "metric_contract" in data


def test_to_prometheus_rules_recording_and_pending():
    rules = _config_30d().to_prometheus_rules()
    assert "slo:burn_rate:ratio_1h" in rules
    assert "slo:burn_rate:ratio_5h" in rules
    assert "for: 2m" in rules
    assert "env: production" in rules
    assert "sli_type: availability" in rules
    assert "and" in rules


def test_prometheus_golden_snippet():
    rules = _config_30d().to_prometheus_rules()
    golden = (GOLDEN_DIR / "prometheus_checkout_snippet.yml").read_text(encoding="utf-8")
    for line in golden.strip().splitlines():
        assert line in rules, f"missing golden line: {line}"


def test_default_critical_fast_burn_is_14_4x_for_30d():
    critical = next(w for w in _config_30d().windows if w.name == "Critical Fast Burn")
    assert pytest.approx(critical.burn_rate, rel=1e-3) == 14.4
    assert critical.short_window_hours == 1
    assert critical.long_window_hours == 5


def test_windows_clamped_to_compliance_window():
    calc = BurnRateCalculator(slo_target=0.999, compliance_window_days=7)
    config = AlertConfigGenerator(calc).generate(service="checkout", slo_name="availability")
    assert all(w.long_window_hours <= 7 * 24 for w in config.windows)
    assert all(w.short_window_hours <= w.long_window_hours for w in config.windows)


def test_datadog_monitors_formula_dual_window():
    monitors = json.loads(_config_30d().to_datadog_monitors())
    assert len(monitors) == 4
    critical = monitors[0]
    assert critical["type"] == "query alert"
    assert "formula(" in critical["query"]
    assert "query1" in critical["query"] and "query2" in critical["query"]
    variables = critical["options"]["variables"]
    assert len(variables) == 2
    assert "last_1h" in variables[0]["query"]
    assert "last_5h" in variables[1]["query"]
    assert critical["options"]["short_window_hours"] == 1
    assert critical["options"]["long_window_hours"] == 5
    assert "env:production" in critical["tags"]
