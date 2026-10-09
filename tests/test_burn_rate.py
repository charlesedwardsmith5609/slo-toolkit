"""Tests for BurnRateCalculator."""
import pytest
from slo_toolkit.burn_rate import BurnRateCalculator


@pytest.fixture
def calc_99_9():
    """99.9% SLO over 30 days."""
    return BurnRateCalculator(slo_target=0.999, compliance_window_days=30)


def test_zero_errors_is_ok(calc_99_9):
    result = calc_99_9.calculate(error_rate=0.0)
    assert result.burn_rate == 0.0
    assert result.status == "OK"


def test_sustainable_burn_rate(calc_99_9):
    """Error rate exactly at budget = burn rate of 1."""
    result = calc_99_9.calculate(error_rate=0.001)
    assert pytest.approx(result.burn_rate, rel=1e-3) == 1.0
    assert result.status == "ELEVATED"


def test_critical_burn_rate(calc_99_9):
    """14.4x burn rate should be CRITICAL."""
    critical_error_rate = 0.001 * 14.4
    result = calc_99_9.calculate(error_rate=critical_error_rate)
    assert result.burn_rate >= 14.4
    assert result.status == "CRITICAL"


def test_budget_exhausted(calc_99_9):
    result = calc_99_9.calculate(error_rate=0.005, budget_consumed_fraction=1.0)
    assert result.status == "EXHAUSTED"
    assert result.budget_remaining_pct == 0.0


def test_time_to_exhaustion_at_1x(calc_99_9):
    """At exactly 1x burn rate, exhaustion equals full compliance window."""
    result = calc_99_9.calculate(error_rate=0.001)
    assert pytest.approx(result.time_to_exhaustion_hours, rel=0.01) == 30 * 24


def test_invalid_slo_target():
    with pytest.raises(ValueError):
        BurnRateCalculator(slo_target=1.5)


def test_invalid_error_rate(calc_99_9):
    with pytest.raises(ValueError):
        calc_99_9.calculate(error_rate=1.5)


def test_burn_rate_for_alert_threshold(calc_99_9):
    """2% budget in 1h for 30d window = 14.4x burn rate."""
    br = calc_99_9.burn_rate_for_alert_threshold(
        budget_fraction=0.02, window_hours=1
    )
    assert pytest.approx(br, rel=1e-3) == 14.4


def test_status_thresholds_scale_with_window():
    """7-day window CRITICAL/WARNING thresholds are not the 30d 14.4x / 6.0x values."""
    calc = BurnRateCalculator(slo_target=0.999, compliance_window_days=7)
    assert pytest.approx(calc.critical_burn_rate, rel=1e-3) == 3.36  # 0.02 * 168 / 1
    assert pytest.approx(calc.warning_burn_rate, rel=1e-3) == 1.4    # 0.05 * 168 / 6

    # 2x is CRITICAL on a 7d window (threshold 3.36 is higher — 2x is only ELEVATED/WARNING)
    result_elevated = calc.calculate(error_rate=0.001 * 2.0)
    assert result_elevated.status == "WARNING"  # 2.0 >= 1.4 warning, < 3.36 critical

    result_critical = calc.calculate(error_rate=0.001 * 3.36)
    assert result_critical.status == "CRITICAL"
    assert abs(result_critical.burn_rate - 14.4) > 1.0
