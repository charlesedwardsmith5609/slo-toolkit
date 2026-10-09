"""
Command-line interface for slo-toolkit.

Usage examples:

  slo-toolkit burn-rate --slo 0.999 --error-rate 0.005
  slo-toolkit burn-rate --slo 0.999 --bad 25 --total 10000
  slo-toolkit alerts --slo 0.999 --service checkout --format prometheus --env production
  slo-toolkit compliance --slo 0.999 --total 1000000 --errors 250
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from typing import List, Optional

from .alert_config import AlertConfigGenerator, MetricContract
from .burn_rate import BurnRateCalculator
from .compliance import CompliancePeriod, SLOComplianceReport
from .types import SLIType


def cmd_burn_rate(args: argparse.Namespace) -> None:
    calc = BurnRateCalculator(
        slo_target=args.slo,
        compliance_window_days=args.window,
        sli_type=args.sli_type,
    )
    if args.bad is not None or args.total is not None:
        if args.bad is None or args.total is None:
            print("error: --bad and --total must be provided together", file=sys.stderr)
            sys.exit(2)
        if args.error_rate is not None:
            print("error: use either --error-rate or --bad/--total, not both", file=sys.stderr)
            sys.exit(2)
        result = calc.calculate_from_counts(
            bad_events=args.bad,
            total_events=args.total,
            budget_consumed_fraction=args.consumed,
        )
    else:
        if args.error_rate is None:
            print("error: provide --error-rate or --bad/--total", file=sys.stderr)
            sys.exit(2)
        result = calc.calculate(
            error_rate=args.error_rate,
            budget_consumed_fraction=args.consumed,
        )

    if args.json:
        print(
            json.dumps(
                {
                    "burn_rate": round(result.burn_rate, 4),
                    "status": result.status.value,
                    "sli_type": result.sli_type.value,
                    "budget_remaining_pct": round(result.budget_remaining_pct, 2),
                    "time_to_exhaustion_hours": (
                        round(result.time_to_exhaustion_hours, 1)
                        if result.time_to_exhaustion_hours is not None
                        else None
                    ),
                    "bad_events": result.bad_events,
                    "total_events": result.total_events,
                },
                indent=2,
            )
        )
    else:
        print(result)


def cmd_alerts(args: argparse.Namespace) -> None:
    calc = BurnRateCalculator(
        slo_target=args.slo,
        compliance_window_days=args.window,
        sli_type=args.sli_type,
    )
    contract = MetricContract(
        prometheus_metric=args.metric,
        environment=args.env,
    )
    gen = AlertConfigGenerator(calc)
    config = gen.generate(
        service=args.service,
        slo_name=args.name,
        environment=args.env,
        metric_contract=contract,
    )

    if args.format == "json":
        print(config.to_json())
    elif args.format == "prometheus":
        print(config.to_prometheus_rules())
    elif args.format == "datadog":
        print(config.to_datadog_monitors())
    else:
        for w in config.windows:
            print(
                f"{w.name:<25}  burn_rate≥{w.burn_rate:>6.1f}x  "
                f"short={w.short_window_hours}h / long={w.long_window_hours}h  "
                f"[{w.severity.value.upper()}]"
            )


def cmd_compliance(args: argparse.Namespace) -> None:
    if args.errors > args.total:
        print("error: --errors cannot exceed --total", file=sys.stderr)
        sys.exit(2)
    if args.total < 0 or args.errors < 0:
        print("error: --total and --errors must be non-negative", file=sys.stderr)
        sys.exit(2)

    now = datetime.datetime.now(datetime.timezone.utc)
    period = CompliancePeriod(
        start=now - datetime.timedelta(days=args.window),
        end=now,
        total_requests=args.total,
        error_requests=args.errors,
    )
    report = SLOComplianceReport(
        slo_target=args.slo,
        compliance_window_days=args.window,
        periods=[period],
        sli_type=args.sli_type,
    )
    if args.json:
        hours = float(args.window * 24)
        print(
            json.dumps(
                {
                    "compliant": report.compliant,
                    "sli_type": report.sli_type.value,
                    "observed_error_rate": round(report.observed_error_rate, 6),
                    "rate_budget_ratio": round(report.rate_budget_ratio, 4),
                    "budget_remaining_pct": round(report.error_budget_remaining_pct, 2),
                    "cumulative_budget_consumed_pct": round(
                        report.cumulative_budget_consumed_fraction(hours) * 100, 2
                    ),
                },
                indent=2,
            )
        )
    else:
        print(report.summary())


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="slo-toolkit",
        description="SLO burn rate calculator and alert config generator",
    )
    parser.add_argument("--version", action="version", version="0.2.0")
    sub = parser.add_subparsers(dest="command", required=True)

    sli_choices = [t.value for t in SLIType]

    br = sub.add_parser("burn-rate", help="Calculate current burn rate")
    br.add_argument("--slo", type=float, default=0.999, help="SLO target (default: 0.999)")
    br.add_argument("--error-rate", type=float, default=None, help="Observed error rate (0.0–1.0)")
    br.add_argument("--bad", type=int, default=None, help="Bad event count")
    br.add_argument("--total", type=int, default=None, help="Total event count")
    br.add_argument("--window", type=int, default=30, help="Compliance window in days")
    br.add_argument("--consumed", type=float, default=0.0, help="Cumulative budget spent (0–1)")
    br.add_argument("--sli-type", choices=sli_choices, default=SLIType.AVAILABILITY.value)
    br.add_argument("--json", action="store_true", help="Output as JSON")
    br.set_defaults(func=cmd_burn_rate)

    al = sub.add_parser("alerts", help="Generate multi-window burn rate alert config")
    al.add_argument("--slo", type=float, default=0.999)
    al.add_argument("--window", type=int, default=30)
    al.add_argument("--service", required=True)
    al.add_argument("--name", default="availability")
    al.add_argument("--env", default="production", help="Environment label")
    al.add_argument("--metric", default="http_requests_total", help="Prometheus metric name")
    al.add_argument("--sli-type", choices=sli_choices, default=SLIType.AVAILABILITY.value)
    al.add_argument(
        "--format",
        choices=["table", "json", "prometheus", "datadog"],
        default="table",
    )
    al.set_defaults(func=cmd_alerts)

    co = sub.add_parser("compliance", help="Check SLO compliance from request counts")
    co.add_argument("--slo", type=float, default=0.999)
    co.add_argument("--window", type=int, default=30)
    co.add_argument("--total", type=int, required=True)
    co.add_argument("--errors", type=int, required=True)
    co.add_argument("--sli-type", choices=sli_choices, default=SLIType.AVAILABILITY.value)
    co.add_argument("--json", action="store_true")
    co.set_defaults(func=cmd_compliance)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
