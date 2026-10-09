"""Tests for SLO compliance reporting and end-of-window projection."""
import datetime

import pytest

from slo_toolkit.compliance import CompliancePeriod, SLOComplianceReport
from slo_toolkit.types import BurnRateStatus, ProjectionMode, SLIType


UTC = datetime.timezone.utc


@pytest.fixture
def compliant_report():
    now = datetime.datetime(2026, 1, 31, tzinfo=UTC)
    period = CompliancePeriod(
        start=now - datetime.timedelta(days=30),
        end=now,
        total_requests=1_000_000,
        error_requests=250,  # 0.025% vs 0.1% budget → ratio 0.25
    )
    return SLOComplianceReport(
        slo_target=0.999,
        compliance_window_days=30,
        periods=[period],
        sli_type=SLIType.AVAILABILITY,
    )


def test_compliant_budget_remaining(compliant_report):
    assert compliant_report.compliant is True
    assert pytest.approx(compliant_report.observed_error_rate, rel=1e-6) == 0.00025
    assert pytest.approx(compliant_report.rate_budget_ratio, rel=1e-3) == 0.25
    assert pytest.approx(compliant_report.error_budget_remaining_pct, rel=1e-3) == 75.0


def test_cumulative_budget_scales_with_elapsed(compliant_report):
    # At full window, cumulative == rate ratio.
    full = compliant_report.cumulative_budget_consumed_fraction(30 * 24)
    assert pytest.approx(full, rel=1e-3) == 0.25

    # At 7/30 of the window with same rate, only ~5.8% of absolute allowance used.
    early = compliant_report.cumulative_budget_consumed_fraction(7 * 24)
    assert pytest.approx(early, rel=1e-3) == 0.25 * (7 / 30)
    assert early < full


def test_breached_when_errors_exceed_budget():
    now = datetime.datetime(2026, 1, 31, tzinfo=UTC)
    report = SLOComplianceReport(
        slo_target=0.999,
        compliance_window_days=30,
        periods=[
            CompliancePeriod(
                start=now - datetime.timedelta(days=30),
                end=now,
                total_requests=1_000_000,
                error_requests=2_000,
            )
        ],
    )
    assert report.compliant is False
    assert report.error_budget_remaining_pct == 0.0


def test_constant_rate_projection_matches_observed(compliant_report):
    proj = compliant_report.project_end_of_window(
        hours_elapsed=7 * 24, mode=ProjectionMode.CONSTANT_RATE
    )
    assert proj.will_comply is True
    assert pytest.approx(proj.projected_error_rate, rel=1e-6) == (
        compliant_report.observed_error_rate
    )
    assert proj.mode is ProjectionMode.CONSTANT_RATE


def test_time_pace_projection_can_breach_early(compliant_report):
    proj = compliant_report.project_end_of_window(
        hours_elapsed=7 * 24, mode=ProjectionMode.TIME_PACE
    )
    assert proj.will_comply is False
    assert proj.projected_error_rate > compliant_report.observed_error_rate


def test_projection_rejects_negative_hours(compliant_report):
    with pytest.raises(ValueError):
        compliant_report.project_end_of_window(hours_elapsed=-1)


def test_period_rejects_errors_above_total():
    now = datetime.datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValueError):
        CompliancePeriod(
            start=now,
            end=now + datetime.timedelta(hours=1),
            total_requests=10,
            error_requests=11,
        )


def test_period_requires_timezone():
    naive = datetime.datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        CompliancePeriod(
            start=naive,
            end=naive + datetime.timedelta(hours=1),
            total_requests=10,
            error_requests=0,
        )


def test_highest_severity_period():
    t0 = datetime.datetime(2026, 1, 1, tzinfo=UTC)
    periods = [
        CompliancePeriod(t0, t0 + datetime.timedelta(hours=1), 10_000, 5),
        CompliancePeriod(
            t0 + datetime.timedelta(hours=1),
            t0 + datetime.timedelta(hours=2),
            10_000,
            200,  # 2% errors → high burn
        ),
    ]
    report = SLOComplianceReport(
        slo_target=0.999, compliance_window_days=30, periods=periods
    )
    hotspot = report.highest_severity_period()
    assert hotspot is not None
    period, br = hotspot
    assert period.error_requests == 200
    assert br.status in (BurnRateStatus.CRITICAL, BurnRateStatus.WARNING)


def test_from_prometheus_samples_ok():
    t0 = datetime.datetime(2026, 1, 1, tzinfo=UTC)
    samples = [
        {"timestamp": t0, "total": 1000, "errors": 1},
        {"timestamp": t0 + datetime.timedelta(hours=1), "total": 2000, "errors": 2},
        {"timestamp": t0 + datetime.timedelta(hours=2), "total": 3000, "errors": 5},
    ]
    report = SLOComplianceReport.from_prometheus_samples(
        slo_target=0.999, compliance_window_days=30, samples=samples
    )
    assert len(report.periods) == 2
    assert report.total_requests == 2000
    assert report.total_errors == 4


def test_from_prometheus_samples_rejects_negative_delta():
    t0 = datetime.datetime(2026, 1, 1, tzinfo=UTC)
    samples = [
        {"timestamp": t0, "total": 2000, "errors": 5},
        {"timestamp": t0 + datetime.timedelta(hours=1), "total": 1000, "errors": 1},
    ]
    with pytest.raises(ValueError, match="negative counter delta"):
        SLOComplianceReport.from_prometheus_samples(
            slo_target=0.999, compliance_window_days=30, samples=samples
        )
