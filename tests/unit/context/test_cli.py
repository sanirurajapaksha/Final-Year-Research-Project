import json

from argus.context.__main__ import main


def test_cli_prints_the_scenario_01_anomaly_set(capsys):
    assert main([]) == 0
    out = capsys.readouterr()
    assert len(json.loads(out.out)) == 8
    assert "8 anomalies from 27 records" in out.err


def test_cli_reports_a_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "missing.json")]) == 1
    assert "can't read fixture" in capsys.readouterr().err


def test_cli_reports_invalid_telemetry(tmp_path, capsys):
    path = tmp_path / "bad.json"
    path.write_text(
        json.dumps({"source": "x", "collected_at": "2026-10-10T10:00:00Z", "records": [{"kind": "event"}]}),
        encoding="utf-8",
    )
    assert main([str(path)]) == 1
    assert "invalid telemetry" in capsys.readouterr().err
