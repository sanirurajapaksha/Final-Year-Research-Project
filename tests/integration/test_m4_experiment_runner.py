"""Exercise the experiment CLI in real clean, detached and dirty Git repositories."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT = Path("experiments/2026-10-13_m4_contract_v1")


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def checkout(tmp_path):
    repo = tmp_path / "checkout"
    for directory in (Path("src"), Path("data/fixtures/m1/scenario_01")):
        shutil.copytree(
            ROOT / directory,
            repo / directory,
            ignore=shutil.ignore_patterns("__pycache__", "*.egg-info"),
        )
    (repo / EXPERIMENT).mkdir(parents=True)
    shutil.copyfile(ROOT / EXPERIMENT / "run.py", repo / EXPERIMENT / "run.py")
    git(repo, "init", "--initial-branch=review-test")
    git(repo, "add", ".")
    git(
        repo,
        "-c",
        "user.name=Runner Test",
        "-c",
        "user.email=runner@example.invalid",
        "commit",
        "-m",
        "fixture",
    )
    return repo


def run(repo: Path, output: Path):
    return subprocess.run(
        [sys.executable, str(repo / EXPERIMENT / "run.py"), "--output-dir", str(output)],
        cwd=repo,
        env=dict(os.environ, PYTHONPATH=str(repo / "src"), PYTHONDONTWRITEBYTECODE="1"),
        capture_output=True,
        text=True,
        timeout=30,
    )


@pytest.mark.parametrize("state", ["detached", "no-upstream", "upstream"])
def test_clean_checkout_reproduces_saved_payloads(checkout, tmp_path, state):
    commit = git(checkout, "rev-parse", "HEAD")
    if state == "detached":
        git(checkout, "checkout", "--detach", commit)
    elif state == "upstream":
        git(checkout, "branch", "tracking-source")
        git(checkout, "branch", "--set-upstream-to=tracking-source")
    output = tmp_path / "output"
    result = run(checkout, output)
    assert result.returncode == 0, result.stderr
    config = json.loads((output / "config.json").read_bytes())
    assert config["source_commit"] == commit
    assert config["source_state"] == "clean working tree"
    assert config["branch"] == (None if state == "detached" else "review-test")
    assert config["upstream"] == ("tracking-source" if state == "upstream" else None)
    for filename in ("compact.json", "default.json", "telemetry.tsv"):
        assert (output / "results" / filename).read_bytes() == (
            ROOT / EXPERIMENT / "results" / filename
        ).read_bytes()
    assert json.loads((output / "results/summary.json").read_bytes()) == json.loads(
        (ROOT / EXPERIMENT / "results/summary.json").read_bytes()
    )
    assert git(checkout, "status", "--porcelain=v1", "--untracked-files=all") == ""
    saved = {path: path.read_bytes() for path in output.rglob("*") if path.is_file()}
    repeated = run(checkout, output)
    assert repeated.returncode == 2
    assert "saved evidence exists" in repeated.stderr
    assert all(path.read_bytes() == content for path, content in saved.items())


@pytest.mark.parametrize("tracked", [True, False])
def test_dirty_checkout_is_rejected_before_output_creation(checkout, tmp_path, tracked):
    path = checkout / EXPERIMENT / "run.py" if tracked else checkout / "untracked.txt"
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n# dirty working tree\n")
    output = tmp_path / "output"
    result = run(checkout, output)
    assert result.returncode == 2
    assert "clean Git working tree required" in result.stderr
    assert not output.exists()
