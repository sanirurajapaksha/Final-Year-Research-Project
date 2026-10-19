import json

import pytest

from argus.orchestration.fake_model_demo import main


@pytest.mark.parametrize(
    "budget,exit_code,spent,last_status", [(17, 0, 17, "succeeded"), (15, 1, 13, "budget_exhausted")]
)
def test_fake_demo_success_and_budget_stop(capsys, budget, exit_code, spent, last_status):
    assert main(["--budget", str(budget)]) == exit_code
    output = json.loads(capsys.readouterr().out)
    assert output["budget"]["spent_units"] == spent
    assert output["budget"]["reserved_units"] == 0
    assert output["tasks"][-1]["status"] == last_status
    assert output["attempts"][0]["status"] == "timeout"
    assert output["attempts"][2]["status"] == "invalid_output"


def test_infeasible_demo_does_not_dispatch(capsys):
    assert main(["--budget", "5"]) == 1
    output = json.loads(capsys.readouterr().out)
    assert output["plan"]["status"] == "infeasible"
    assert output["attempts"] == []
    assert output["budget"]["spent_units"] == 0


def test_invalid_demo_budget(capsys):
    assert main(["--budget", "-1"]) == 2
    assert "fake model demo" in capsys.readouterr().err
