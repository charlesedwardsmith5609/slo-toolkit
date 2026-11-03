"""Property-based tests for burn-rate math invariants."""

from __future__ import annotations

import math

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st
from slo_toolkit.burn_rate import BurnRateCalculator
from slo_toolkit.types import BurnRateStatus

slo_targets = st.floats(min_value=0.9, max_value=0.9999, allow_nan=False, allow_infinity=False)
error_rates = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
nonzero_error_rates = st.floats(
    min_value=1e-9, max_value=1.0, allow_nan=False, allow_infinity=False
)
consumed = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
windows = st.integers(min_value=1, max_value=90)
budget_fractions = st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
window_hours = st.floats(min_value=0.25, max_value=24 * 30, allow_nan=False, allow_infinity=False)

_STATUS_ORDER = {
    BurnRateStatus.OK: 0,
    BurnRateStatus.ELEVATED: 1,
    BurnRateStatus.WARNING: 2,
    BurnRateStatus.CRITICAL: 3,
    BurnRateStatus.EXHAUSTED: 4,
}


@given(slo_target=slo_targets, error_rate=error_rates, window_days=windows, consumed_frac=consumed)
@settings(max_examples=200)
def test_burn_rate_equals_error_rate_over_budget(
    slo_target: float, error_rate: float, window_days: int, consumed_frac: float
) -> None:
    calc = BurnRateCalculator(slo_target=slo_target, compliance_window_days=window_days)
    result = calc.calculate(error_rate=error_rate, budget_consumed_fraction=consumed_frac)
    expected = error_rate / calc.error_budget
    assert result.burn_rate == pytest.approx(expected, rel=1e-9, abs=1e-12)
    assert result.error_budget == pytest.approx(round(1.0 - slo_target, 12))


@given(slo_target=slo_targets, window_days=windows)
@settings(max_examples=100)
def test_error_rate_equal_budget_is_one_x(slo_target: float, window_days: int) -> None:
    calc = BurnRateCalculator(slo_target=slo_target, compliance_window_days=window_days)
    result = calc.calculate(error_rate=calc.error_budget)
    assert result.burn_rate == pytest.approx(1.0, rel=1e-9, abs=1e-12)
    # 1x is always at least ELEVATED; on short windows the scaled WARNING/CRITICAL
    # thresholds can fall below 1.0, so status may be higher.
    assert _STATUS_ORDER[result.status] >= _STATUS_ORDER[BurnRateStatus.ELEVATED]
    assert result.time_to_exhaustion_hours == pytest.approx(
        float(calc.compliance_window_hours), rel=1e-9, abs=1e-9
    )


@given(
    slo_target=slo_targets,
    window_days=windows,
    budget_fraction=budget_fractions,
    hours=window_hours,
)
@settings(max_examples=150)
def test_alert_threshold_formula(
    slo_target: float, window_days: int, budget_fraction: float, hours: float
) -> None:
    calc = BurnRateCalculator(slo_target=slo_target, compliance_window_days=window_days)
    br = calc.burn_rate_for_alert_threshold(budget_fraction, hours)
    expected = (budget_fraction * calc.compliance_window_hours) / hours
    assert br == pytest.approx(expected, rel=1e-9, abs=1e-12)


@given(
    slo_target=slo_targets,
    window_days=windows,
    total=st.integers(min_value=0, max_value=100_000),
    bad=st.integers(min_value=0, max_value=100_000),
)
@settings(max_examples=150)
def test_counts_match_rate_path(slo_target: float, window_days: int, total: int, bad: int) -> None:
    assume(bad <= total)
    calc = BurnRateCalculator(slo_target=slo_target, compliance_window_days=window_days)
    from_counts = calc.calculate_from_counts(bad_events=bad, total_events=total)
    rate = bad / total if total > 0 else 0.0
    from_rate = calc.calculate(error_rate=rate)
    assert from_counts.burn_rate == pytest.approx(from_rate.burn_rate, rel=1e-9, abs=1e-12)
    assert from_counts.status == from_rate.status
    assert from_counts.error_rate == pytest.approx(rate, rel=1e-9, abs=1e-12)


@given(slo_target=slo_targets, window_days=windows, error_rate=error_rates)
@settings(max_examples=150)
def test_status_thresholds_are_monotonic(
    slo_target: float, window_days: int, error_rate: float
) -> None:
    """Higher burn rate never yields a less severe status (when budget remains)."""
    calc = BurnRateCalculator(slo_target=slo_target, compliance_window_days=window_days)
    lower = calc.calculate(error_rate=error_rate * 0.5)
    higher = calc.calculate(error_rate=error_rate)
    assert _STATUS_ORDER[higher.status] >= _STATUS_ORDER[lower.status]


@given(slo_target=slo_targets, window_days=windows, error_rate=nonzero_error_rates)
@settings(max_examples=100)
def test_time_to_exhaustion_scales_inversely_with_burn(
    slo_target: float, window_days: int, error_rate: float
) -> None:
    calc = BurnRateCalculator(slo_target=slo_target, compliance_window_days=window_days)
    result = calc.calculate(error_rate=error_rate)
    assert result.time_to_exhaustion_hours is not None
    assert result.burn_rate > 0
    assume(math.isfinite(result.burn_rate))
    expected = calc.compliance_window_hours / result.burn_rate
    assert result.time_to_exhaustion_hours == pytest.approx(expected, rel=1e-9, abs=1e-9)
    assert math.isfinite(result.time_to_exhaustion_hours)
