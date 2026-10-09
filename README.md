# slo-toolkit

Offline SLO burn rate calculator, multi-window alert config generator, and compliance reporter.

Built on the multi-window burn rate alerting strategy from the [Google SRE Workbook](https://sre.google/workbook/alerting-on-slos/). It emits **versioned JSON**, **Prometheus** rules (with recording rules + `for:`), and **Datadog formula** monitor JSON — it does not scrape metrics or call vendor APIs.

## Scope

| Included | Not included |
|----------|--------------|
| Burn rate from rates or good/bad counts | Live metric collection |
| Multi-window alert thresholds (window-clamped) | Vendor SDKs / apply APIs |
| Prometheus + Datadog config export | Ticketing / paging integrations |
| Compliance, cumulative budget, EOW projection | Dashboards or a UI |
| SLI types: availability / latency / freshness | |

**Budget vocabulary (important):**

- **Burn rate** — instantaneous pace vs sustainable rate (`error_rate / error_budget`).
- **Rate / budget ratio** — same idea over an observed sample; not calendar progress.
- **Cumulative budget consumed** — absolute allowance used so far assuming constant RPS: `ratio × (elapsed / window)`.
- **EOW projection `constant_rate`** (default) — if the observed *rate* continues, end-of-window rate ≈ observed rate (correct for request-based SLIs like checkout availability).
- **EOW projection `time_pace`** — calendar heuristic `ratio × window/elapsed`; useful for storytelling, easy to misuse on request SLIs.

Status thresholds (CRITICAL / WARNING) scale with the compliance window (2% budget in 1h, 5% in 6h). On 30 days that is 14.4× / 6.0×.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

### Burn rate

```bash
slo-toolkit burn-rate --slo 0.999 --error-rate 0.005
slo-toolkit burn-rate --slo 0.999 --bad 50 --total 10000 --json
```

### Alert config

```bash
slo-toolkit alerts --slo 0.999 --service checkout --env production
slo-toolkit alerts --slo 0.999 --service checkout --format prometheus --metric http_requests_total
slo-toolkit alerts --slo 0.999 --service checkout --format datadog --env production
slo-toolkit alerts --slo 0.999 --service checkout --format json   # schema_version: 1.0
```

### Compliance

```bash
slo-toolkit compliance --slo 0.999 --total 1000000 --errors 250 --sli-type availability
```

## Python API

```python
from slo_toolkit import (
    BurnRateCalculator,
    AlertConfigGenerator,
    MetricContract,
    ProjectionMode,
    SLIType,
)

calc = BurnRateCalculator(
    slo_target=0.999,
    compliance_window_days=30,
    sli_type=SLIType.AVAILABILITY,
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
pytest -q
```

GitHub Actions runs the suite on Python 3.9–3.12.

## License

MIT — see [LICENSE](LICENSE).
