"""
Command-line interface for slo-toolkit.

Usage examples:

  # Calculate burn rate for a 99.9% SLO with 0.5% observed error rate
  slo-toolkit burn-rate --slo 0.999 --error-rate 0.005

  # Generate multi-window alert config and emit Prometheus rules
  slo-toolkit alerts --slo 0.999 --service payments --format prometheus

  # Check compliance given total/error request counts
  slo-toolkit compliance --slo 0.999 --total 1000000 --errors 250
"""

from __future__ import annotations

import argparse
import json
import datetime
import sys
from typing import List, Optional

from .burn_rate import BurnRateCalculator
from .alert_config import AlertConfigGenerator
from .compliance import SLOComplianceReport, CompliancePeriod


def cmd_burn_rate(args: argparse.Namespace) -> None:
    calc = BurnRateCalculator(
        slo_target=args.slo,
        compliance_window_days=args.window,
    )
    result = calc.calculate(
        error_rate=args.error_rate,
        budget_consumed_fraction=args.consumed,
    )
    if args.json:
        print(json.dumps({
            "burn_rate": round(result.burn_rate, 4),
            "status": result.status,
            "budget_remaining_pct": round(result.budget_remaining_pct, 2),
            "time_to_exhaustion_hours": (
                round(result.time_to_exhaustion_hours, 1)
                if result.time_to_exhaustion_hours is not None else None
            ),
        }, indent=2))
    else:
        print(result)


def cmd_alerts(args: argparse.Namespace) -> None:
    calc = BurnRateCalculator(
        slo_target=args.slo,
        compliance_window_days=args.window,
    )
    gen = AlertConfigGenerator(calc)
    config = gen.generate(service=args.service, slo_name=args.name)

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
                f"[{w.severity.upper()}]"
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
    )
    if args.json:
        print(json.dumps({
            "compliant": report.compliant,
            "observed_error_rate": round(report.observed_error_rate, 6),
            "budget_remaining_pct": round(report.error_budget_remaining_pct, 2),
            "budget_consumed_pct": round(report.error_budget_consumed_fraction * 100, 2),
        }, indent=2))
    else:
        print(report.summary())


def main(argv: Optional[List[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="slo-toolkit",
        description="SLO burn rate calculator and alert config generator",
    )
    parser.add_argument("--version", action="version", version="0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    # burn-rate subcommand
    br = sub.add_parser("burn-rate", help="Calculate current burn rate")
    br.add_argument("--slo", type=float, default=0.999, help="SLO target (default: 0.999)")
    br.add_argument("--error-rate", type=float, required=True, help="Observed error rate (0.0–1.0)")
    br.add_argument("--window", type=int, default=30, help="Compliance window in days (default: 30)")
    br.add_argument("--consumed", type=float, default=0.0, help="Fraction of budget already consumed")
    br.add_argument("--json", action="store_true", help="Output as JSON")
    br.set_defaults(func=cmd_burn_rate)

    # alerts subcommand
    al = sub.add_parser("alerts", help="Generate multi-window burn rate alert config")
    al.add_argument("--slo", type=float, default=0.999, help="SLO target (default: 0.999)")
    al.add_argument("--window", type=int, default=30, help="Compliance window in days")
    al.add_argument("--service", required=True, help="Service name")
    al.add_argument("--name", default="availability", help="SLO name (default: availability)")
    al.add_argument(
        "--format",
        choices=["table", "json", "prometheus", "datadog"],
        default="table",
        help="Output format (default: table)",
    )
    al.set_defaults(func=cmd_alerts)

    # compliance subcommand
    co = sub.add_parser("compliance", help="Check SLO compliance from request counts")
    co.add_argument("--slo", type=float, default=0.999, help="SLO target")
    co.add_argument("--window", type=int, default=30, help="Compliance window in days")
    co.add_argument("--total", type=int, required=True, help="Total requests in window")
    co.add_argument("--errors", type=int, required=True, help="Error requests in window")
    co.add_argument("--json", action="store_true", help="Output as JSON")
    co.set_defaults(func=cmd_compliance)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
