"""CLI smoke tests."""
import json

import pytest

from slo_toolkit.cli import main


def test_burn_rate_json(capsys):
    main(["burn-rate", "--slo", "0.999", "--error-rate", "0.001", "--json"])
    out = json.loads(capsys.readouterr().out)
    assert pytest.approx(out["burn_rate"], rel=1e-3) == 1.0
    assert out["status"] == "ELEVATED"


def test_compliance_rejects_errors_above_total(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["compliance", "--total", "100", "--errors", "150"])
    assert exc.value.code == 2
    err = capsys.readouterr().err
    assert "errors cannot exceed" in err
