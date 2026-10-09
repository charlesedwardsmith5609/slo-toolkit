# slo-toolkit

Offline SLO burn rate calculator, multi-window alert config generator, and compliance reporter.

Built on the multi-window burn rate alerting strategy from the [Google SRE Workbook](https://sre.google/workbook/alerting-on-slos/). It emits **Prometheus** rules, **Datadog** monitor JSON, and generic JSON — it does not scrape metrics or talk to those APIs.

## Scope

| Included | Not included |
|----------|--------------|
| Burn rate + time-to-exhaustion | Live metric collection |
| Multi-window alert thresholds | Chronosphere / vendor SDKs |
| Prometheus + Datadog config export | Ticketing / paging integrations |
| Compliance summary from request counts | Dashboards or a UI |

Status thresholds (CRITICAL / WARNING) scale with the compliance window using the same formulas as the default alert windows (2% budget in 1h, 5% in 6h). On a 30-day window that is 14.4× / 6.0×; on a shorter window the numbers are lower.

## Install

```bash
pip install -e .
# or with test deps:
pip install -e ".[dev]"
```

## Usage

### Burn rate

```bash
# 0.5% error rate against a 99.9% SLO
slo-toolkit burn-rate --slo 0.999 --error-rate 0.005

# Burn Rate: 5.00x  |  Budget remaining: 100.0%  |  Time to exhaustion: 144.0h  |  Status: WARNING

# JSON output
slo-toolkit burn-rate --slo 0.999 --error-rate 0.005 --json
```

### Alert config

```bash
# Generate multi-window thresholds as a table
slo-toolkit alerts --slo 0.999 --service payments

# Emit Prometheus alerting rules (short AND long window must fire)
slo-toolkit alerts --slo 0.999 --service payments --format prometheus

# Emit Datadog monitor definitions (same dual-window intent)
slo-toolkit alerts --slo 0.999 --service payments --format datadog
```

### Compliance check

```bash
# 1M requests, 250 errors, 99.9% SLO target
slo-toolkit compliance --slo 0.999 --total 1000000 --errors 250

# SLO Compliance Report
# ────────────────────────────────────────
# SLO Target:            99.900%
# Status:                COMPLIANT
# Observed error rate:   0.0250%
# Budget remaining:      75.0%
```

## Python API

```python
from slo_toolkit import BurnRateCalculator, AlertConfigGenerator

# 99.95% SLO, 30-day window
calc = BurnRateCalculator(slo_target=0.9995, compliance_window_days=30)

# Current burn rate
result = calc.calculate(error_rate=0.001)
print(result)

# Multi-window alert thresholds
gen = AlertConfigGenerator(calc)
config = gen.generate(service="api-gateway", slo_name="availability")
print(config.to_prometheus_rules())
print(config.to_json())
```

## Multi-window alert thresholds (99.9% SLO, 30-day window)

| Alert              | Short window | Long window | Budget consumed | Burn rate | Severity |
|--------------------|-------------|-------------|-----------------|-----------|----------|
| Critical Fast Burn | 1h          | 5h          | 2%              | 14.4×     | Page     |
| High Slow Burn     | 6h          | 30h         | 5%              | 6.0×      | Page     |
| Medium Burn        | 24h         | 72h         | 10%             | 3.0×      | Ticket   |
| Low Burn           | 72h         | 168h        | 10%             | 1.0×      | Info     |

## Tests

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT — see [LICENSE](LICENSE).
