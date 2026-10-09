"""CLI smoke tests."""
import json

import pytest

from slo_toolkit.cli import main
from slo_toolkit.types import BurnRateStatus


def test_burn_rate_json(capsys):
    main(["burn-rate", "--slo", "0.999", "--error-rate", "0.001", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert pytest.approx(out["burn_rate"], rel=1e-3) == 1.0
    assert out["status"] == BurnRateStatus.ELEVATED.value


def test_burn_rate_from_counts(capsys):
    main(["burn-rate", "--slo", "0.999", "--bad", "10", "--total", "10000", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert out["bad_events"] == 10
    assert out["total_events"] == 10000
    assert pytest.approx(out["burn_rate"], rel=1e-3) == 1.0


def test_compliance_rejects_errors_above_total(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["compliance", "--total", "100", "--errors", "150"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "errors cannot exceed" in err


def test_alerts_json_schema(capsys):
    main(
        [
            "alerts",
            "--service",
            "checkout",
            "--format",
            "json",
            "--env",
            "staging",
        ]
    )
    data = json.loads(capsys.readouterr().out)
    assert data["schema_version"] == "1.0"
    assert data["environment"] == "staging"
