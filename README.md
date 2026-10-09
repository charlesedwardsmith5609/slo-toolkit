# slo-toolkit

Offline SLO burn rate calculator, multi-window alert config generator, and compliance reporter.

**In one sentence:** you give it an SLO target and how many requests failed; it tells you how fast you are burning error budget and can emit Prometheus / Datadog alert configs. It does **not** scrape metrics or call vendor APIs.

Built on the multi-window burn rate alerting strategy from the [Google SRE Workbook — Alerting on SLOs](https://sre.google/workbook/alerting-on-slos/).

## Quick start

```bash
pip install -e .
slo-toolkit burn-rate --slo 0.999 --error-rate 0.005
```

```text
Burn Rate: 5.00x  |  Budget remaining: 100.0%  |  Time to exhaustion: 144.0h  |  Status: ELEVATED
```

That means: against a 99.9% SLO (0.1% allowed errors), a 0.5% error rate is burning budget **5×** faster than sustainable. At that pace, a full 30-day budget would last about 144 hours. Status values are `OK`, `ELEVATED`, `WARNING`, `CRITICAL`, and `EXHAUSTED`.

## Scope

| Included | Not included |
|----------|--------------|
| Burn rate from rates or good/bad counts | Live metric collection |
| Multi-window alert thresholds (window-clamped) | Vendor SDKs / apply APIs |
| Prometheus + Datadog config export (review before apply) | Ticketing / paging integrations |
| Compliance, cumulative budget, EOW projection | Dashboards or a UI |
| SLI *labels*: availability / latency / freshness | Changing burn-rate math per SLI type |

### Budget vocabulary

| Term | Meaning |
|------|---------|
| **Burn rate** | Instantaneous pace vs sustainable rate: `error_rate / error_budget`. `1.0` = exactly on track. |
| **Rate / budget ratio** | Same idea over an observed sample (`observed_error_rate / error_budget`). **Not** “how far through the calendar month you are.” Prefer this name over the legacy alias `error_budget_consumed_fraction`. |
| **Cumulative budget consumed** | Absolute allowance used so far assuming constant traffic: `ratio × (elapsed / window)`. |
| **EOW `constant_rate`** (default) | If the observed *error rate* continues, end-of-window rate ≈ observed rate. Correct for request-based SLIs (e.g. checkout availability). |
| **EOW `time_pace`** | Calendar heuristic: `ratio × window / elapsed`. Easy to misuse on request SLIs — see worked example below. |

Status thresholds (`CRITICAL` / `WARNING`) scale with the compliance window (2% budget in 1h, 5% in 6h). On a 30-day window that is **14.4×** / **6.0×**.

## Install

```bash
pip install -e .          # runtime
pip install -e ".[dev]"   # + pytest
```

## Usage

### Burn rate

```bash
# From an error rate (0.0–1.0)
slo-toolkit burn-rate --slo 0.999 --error-rate 0.005

# From good/bad counts (better when volume is low)
slo-toolkit burn-rate --slo 0.999 --bad 50 --total 10000 --json

# --consumed is cumulative budget already spent (0–1), not the burn rate
slo-toolkit burn-rate --slo 0.999 --error-rate 0.005 --consumed 0.4
```

### Alert config

Generated rules/monitors are templates — **review before apply** (metric names, runbooks, Datadog formula queries).

```bash
slo-toolkit alerts --slo 0.999 --service checkout --env production
slo-toolkit alerts --slo 0.999 --service checkout --format prometheus --metric http_requests_total
slo-toolkit alerts --slo 0.999 --service checkout --format datadog --env production
slo-toolkit alerts --slo 0.999 --service checkout --format json   # schema_version: 1.0
```

### Compliance

`--total` / `--errors` are treated as counts over `--window` days:

```bash
slo-toolkit compliance --slo 0.999 --total 1000000 --errors 250 --window 30 --sli-type availability
```

### Worked example: `constant_rate` vs `time_pace`

Same data: **1M requests, 250 errors** (0.025% errors) observed over **7 days** of a **30-day**, 99.9% SLO (allowed error rate 0.1%).

```python
from datetime import datetime, timedelta, timezone
from slo_toolkit import (
    CompliancePeriod,
    ProjectionMode,
    SLOComplianceReport,
)

now = datetime(2026, 1, 31, tzinfo=timezone.utc)
report = SLOComplianceReport(
    slo_target=0.999,
    compliance_window_days=30,
    periods=[
        CompliancePeriod(
            start=now - timedelta(days=7),
            end=now,
            total_requests=1_000_000,
            error_requests=250,
        )
    ],
)

# Prefer this for request-based SLIs (checkout, API availability)
constant = report.project_end_of_window(7 * 24, ProjectionMode.CONSTANT_RATE)
# constant.projected_error_rate == 0.00025  → still under 0.001 budget → will_comply True

# Calendar heuristic — same inputs, opposite conclusion
pace = report.project_end_of_window(7 * 24, ProjectionMode.TIME_PACE)
# pace scales "how hard we're burning" by 30/7 → projects a breach → will_comply False
```

If the **error rate** stays at 0.025%, you finish the month compliant. `time_pace` answers a different question (“if this early-window *pace of budget use* continued linearly”) and can scare you incorrectly on request SLIs.

## Python API

```python
from slo_toolkit import (
    BurnRateCalculator,
    AlertConfigGenerator,
    MetricContract,
    ProjectionMode,
    SLIType,
    SLOComplianceReport,
)

calc = BurnRateCalculator(
    slo_target=0.999,
    compliance_window_days=30,
    sli_type=SLIType.AVAILABILITY,  # label only; math is always good/bad or error-rate
)
print(calc.calculate_from_counts(bad_events=25, total_events=100_000))

gen = AlertConfigGenerator(calc)
config = gen.generate(
    service="checkout",
    slo_name="availability",
    environment="production",
    metric_contract=MetricContract(
        prometheus_metric="http_requests_total",
        prometheus_error_selector='status="5xx"',
        environment="production",
    ),
)
print(config.to_prometheus_rules())
```

## Multi-window alert thresholds (99.9% SLO, 30-day window)

| Alert              | Short | Long | Budget | Burn rate | Severity |
|--------------------|-------|------|--------|-----------|----------|
| Critical Fast Burn | 1h    | 5h   | 2%     | 14.4×     | Page     |
| High Slow Burn     | 6h    | 30h  | 5%     | 6.0×      | Page     |
| Medium Burn        | 24h   | 72h  | 10%    | 3.0×      | Ticket   |
| Low Burn           | 72h   | 168h | 10%    | 1.0×      | Info     |

On shorter compliance windows, long detection windows are **clamped** so they never exceed the SLO window.

## Tests / CI

```bash
pip install -e ".[dev]"
pytest -q
```

GitHub Actions runs the suite on Python 3.9–3.12.

## License

MIT — see [LICENSE](LICENSE).
