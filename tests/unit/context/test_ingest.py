import pytest

from argus.context.ingest import IngestError, decode_tsv, parse_records

T = "2026-10-10T10:00:00Z"


def test_parse_records_groups_scenario_01_by_type(scenario_01_batch):
    parsed = parse_records(scenario_01_batch.records)
    assert (len(parsed.metrics), len(parsed.logs), len(parsed.spans), len(parsed.k8s)) == (8, 9, 6, 4)
    assert parsed.total == len(scenario_01_batch.records)


def test_decode_tsv_restores_records_and_leaves_missing_fields_out():
    header = "kind\tservice\tname\tvalue\ttimestamp\tseverity\tmessage\r\n"
    metric = '"""metric"""\t"""cart"""\t"""http_5xx_rate"""\t0.92\t"""2026-10-10T10:00:00Z"""\t\t\r\n'
    log = '"""log"""\t"""cart"""\t\t\t"""2026-10-10T10:00:00Z"""\t"""ERROR"""\t"""a\\tb"""\r\n'
    records = decode_tsv(header + metric + log)
    assert records[0] == {
        "kind": "metric",
        "service": "cart",
        "name": "http_5xx_rate",
        "value": 0.92,
        "timestamp": T,
    }
    assert records[1]["message"] == "a\tb"
    assert "name" not in records[1]


def test_empty_input_gives_no_records():
    assert decode_tsv("") == []
    assert parse_records([]).total == 0


def test_decode_tsv_rejects_a_cell_that_is_not_json():
    with pytest.raises(IngestError, match="row 2"):
        decode_tsv("kind\tservice\r\nmetric\tcart\r\n")


def test_decode_tsv_rejects_a_row_with_the_wrong_number_of_cells():
    with pytest.raises(IngestError, match="row 2 has 1 cells"):
        decode_tsv('kind\tservice\r\n"""metric"""\r\n')


def test_parse_records_rejects_a_record_with_a_missing_field():
    with pytest.raises(IngestError, match="record 0"):
        parse_records([{"kind": "metric", "service": "cart", "name": "cpu_utilization", "timestamp": T}])


def test_parse_records_rejects_an_unknown_kind():
    with pytest.raises(IngestError, match="record 1"):
        parse_records(
            [
                {"kind": "log", "service": "cart", "severity": "INFO", "message": "ok", "timestamp": T},
                {"kind": "event", "object": "pod/cart", "reason": "BackOff"},
            ]
        )
