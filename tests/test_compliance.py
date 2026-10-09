"""Tests for SLO compliance reporting and end-of-window projection."""
import datetime

import pytest

from slo_toolkit.compliance import CompliancePeriod, SLOComplianceReport


@pytest.fixture
def compliant_report():
    now = datetime.datetime(2026, 1, 31, tzinfo=datetime.timezone.utc)
    period = CompliancePeriod(
        start=now - datetime.timedelta(days=30),
        end=now,
        total_requests=1_000_000,
        error_requests=250,  # 0.025% vs 0.1% budget
    )
    return SLOComplianceReport(
        slo_target=0.999,
        compliance_window_days=30,
        periods=[period],
    )


def test_compliant_budget_remaining(compliant_report):
    assert compliant_report.compliant is True
    assert pytest.approx(compliant_report.observed_error_rate, rel=1e-6) == 0.00025
    assert pytest.approx(compliant_report.error_budget_remaining_pct, rel=1e-3) == 75.0


def test_breached_when_errors_exceed_budget():
    now = datetime.datetime(2026, 1, 31, tzinfo=datetime.timezone.utc)
    report = SLOComplianceReport(
        slo_target=0.999,
        compliance_window_days=30,
        periods=[
            CompliancePeriod(
                start=now - datetime.timedelta(days=30),
                end=now,
                total_requests=1_000_000,
                error_requests=2_000,  # 0.2% > 0.1% budget
            )
        ],
    )
    assert report.compliant is False
    assert report.error_budget_remaining_pct == 0.0


def test_projection_extrapolates_with_hours_elapsed(compliant_report):
    """Early in the window, same observed rate projects higher budget pressure."""
    # At full window, projection matches observation and stays compliant.
    rate_full, ok_full = compliant_report.project_end_of_window(hours_elapsed=30 * 24)
    assert ok_full is True
    assert pytest.approx(rate_full, rel=1e-6) == compliant_report.observed_error_rate

    # If this burn were achieved in only 7 days, extrapolating pace would breach.
    rate_early, ok_early = compliant_report.project_end_of_window(hours_elapsed=7 * 24)
    assert ok_early is False
    assert rate_early > compliant_report.observed_error_rate


def test_projection_rejects_negative_hours(compliant_report):
    with pytest.raises(ValueError):
        compliant_report.project_end_of_window(hours_elapsed=-1)


def test_period_rejects_errors_above_total():
    now = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)
    with pytest.raises(ValueError):
        CompliancePeriod(
            start=now,
            end=now + datetime.timedelta(hours=1),
            total_requests=10,
            error_requests=11,
        )
