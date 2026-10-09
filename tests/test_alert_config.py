"""Tests for Prometheus alert rule generation."""
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
