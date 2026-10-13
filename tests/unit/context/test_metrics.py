import pytest

from argus.context.filters import extract_anomalies
from argus.context.ingest import parse_records
from argus.context.metrics import StageCounts, stage_counts
from argus.contracts import AnomalySignal

T = "2026-10-10T10:00:00Z"


def signal(service, name):
    return AnomalySignal(service=service, source="metric", name=name, timestamp=T)


def test_scenario_01_stage1_counts_and_ratios(scenario_01_batch, scenario_01_truth):
    telemetry = parse_records(scenario_01_batch.records)
    stage1_input = len(telemetry.metrics) + len(telemetry.logs) + len(telemetry.k8s)
    counts = stage_counts(
        stage1_input, extract_anomalies(telemetry), scenario_01_truth["stage1_expected"]["relevant"]
    )
    assert counts == StageCounts(raw=21, kept=8, evidence=5, kept_evidence=5)
    assert counts.nrr == pytest.approx(1 - 8 / 21)
    assert counts.labelled_nrr == pytest.approx(13 / 16)
    assert counts.false_prune_rate == 0


def test_evidence_is_matched_as_a_multiset():
    kept = [signal("cart", "log_error")]
    counts = stage_counts(4, kept, [("cart", "log_error"), ("cart", "log_error")])
    assert (counts.kept_evidence, counts.false_prune_rate) == (1, 0.5)


def test_keeping_everything_gives_zero_reduction():
    counts = StageCounts(raw=3, kept=3, evidence=1, kept_evidence=1)
    assert (counts.nrr, counts.labelled_nrr) == (0, 0)


def test_dropping_everything_shows_up_as_false_prunes():
    counts = StageCounts(raw=3, kept=0, evidence=1, kept_evidence=0)
    assert counts.nrr == 1
    assert counts.false_prune_rate == 1


@pytest.mark.parametrize("ratio", ["nrr", "labelled_nrr", "false_prune_rate"])
def test_ratios_are_undefined_on_empty_input(ratio):
    with pytest.raises(ValueError, match="undefined"):
        getattr(StageCounts(raw=0, kept=0, evidence=0, kept_evidence=0), ratio)


def test_labelled_nrr_is_undefined_without_noise():
    with pytest.raises(ValueError, match="noise is 0"):
        _ = StageCounts(raw=2, kept=2, evidence=2, kept_evidence=2).labelled_nrr


@pytest.mark.parametrize(
    "fields",
    [
        {"raw": 2, "kept": 3, "evidence": 0, "kept_evidence": 0},
        {"raw": 2, "kept": 1, "evidence": 3, "kept_evidence": 0},
        {"raw": 2, "kept": 1, "evidence": 2, "kept_evidence": 2},
        {"raw": 2, "kept": -1, "evidence": 0, "kept_evidence": 0},
    ],
)
def test_impossible_counts_are_rejected(fields):
    with pytest.raises(ValueError):
        StageCounts(**fields)
