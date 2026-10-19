from datetime import UTC, datetime, timedelta

import pytest

from argus.context.ingest import IngestError, parse_records
from argus.context.sdg import DEFAULT_LOOKBACK, build_graph, is_error, spans_in_window
from argus.contracts import Span

T = "2026-10-10T10:04:00Z"


def span(service, span_id, parent=None, kind="SERVER", trace="t1", start=T, **status):
    return Span(
        service=service,
        trace_id=trace,
        span_id=span_id,
        parent_span_id=parent,
        operation="op",
        span_kind=kind,
        start_time=start,
        duration_ms=1,
        **status,
    )


def scenario_01_spans(batch):
    return parse_records(batch.records).spans


def test_scenario_01_graph(scenario_01_batch):
    graph = build_graph(scenario_01_spans(scenario_01_batch))
    assert graph.services == {"frontend", "cart", "product-catalog"}
    assert graph.edges == {("frontend", "cart"), ("frontend", "product-catalog")}
    assert graph.failing == {"frontend", "cart"}
    assert graph.entry_point == "frontend"
    assert graph.unseen_callees == 0


def test_scenario_01_failing_path_leaves_out_product_catalog(scenario_01_batch):
    assert build_graph(scenario_01_spans(scenario_01_batch)).failing_path() == {"frontend", "cart"}


@pytest.mark.parametrize(
    "status,failed",
    [
        ({"otel_status_code": "ERROR"}, True),
        ({"http_status_code": 503}, True),
        ({"grpc_status_code": 14}, True),
        ({"http_status_code": 404}, False),
        ({"grpc_status_code": 0, "otel_status_code": "OK"}, False),
        ({}, False),
    ],
)
def test_is_error(status, failed):
    assert is_error(span("cart", "s1", **status)) is failed


def test_callers_are_on_the_failing_path_but_callees_are_not():
    graph = build_graph(
        [
            span("gateway", "a"),
            span("frontend", "b", parent="a"),
            span("cart", "c", parent="b", otel_status_code="ERROR"),
            span("redis", "d", parent="c"),
        ]
    )
    assert graph.failing_path() == {"gateway", "frontend", "cart"}
    assert graph.entry_point == "gateway"


def test_calls_inside_one_service_add_no_edge():
    graph = build_graph([span("cart", "a"), span("cart", "b", parent="a", kind="INTERNAL")])
    assert graph.edges == set()


def test_cyclic_calls_terminate():
    graph = build_graph(
        [
            span("a", "1"),
            span("b", "2", parent="1"),
            span("a", "3", parent="2"),
            span("b", "4", parent="3", otel_status_code="ERROR"),
        ]
    )
    assert graph.edges == {("a", "b"), ("b", "a")}
    assert graph.failing_path() == {"a", "b"}


def test_failed_call_without_a_callee_span_is_counted():
    graph = build_graph(
        [span("frontend", "a"), span("frontend", "b", parent="a", kind="CLIENT", grpc_status_code=14)]
    )
    assert graph.unseen_callees == 1
    assert graph.unseen_callers == {"frontend"}
    assert graph.failing == {"frontend"}


def callee_answers_then_crashes():
    """cart calls redis once successfully, then a later cart call to redis fails with no redis span."""
    return [
        span("cart", "a", trace="ok"),
        span("cart", "b", parent="a", kind="CLIENT", trace="ok"),
        span("redis", "c", parent="b", trace="ok"),
        span("frontend", "d", trace="ok"),
        span("product-catalog", "e", parent="d", trace="ok"),
        span("cart", "x", trace="bad", otel_status_code="ERROR"),
        span("cart", "y", parent="x", kind="CLIENT", trace="bad", otel_status_code="ERROR"),
    ]


def test_possible_unseen_callees_are_what_the_caller_called_elsewhere():
    graph = build_graph(callee_answers_then_crashes())
    assert graph.unseen_callees == 1
    assert graph.possible_unseen_callees() == {"redis"}
    assert "redis" not in graph.failing_path()


def test_no_unseen_callees_means_no_possible_ones(scenario_01_batch):
    assert build_graph(scenario_01_spans(scenario_01_batch)).possible_unseen_callees() == set()


def test_span_whose_parent_is_missing_counts_as_a_root():
    graph = build_graph([span("cart", "b", parent="not-in-batch", otel_status_code="ERROR")])
    assert graph.entry_point == "cart"


def test_entry_point_is_the_most_common_failed_root():
    graph = build_graph(
        [
            span("web", "1", trace="t1", otel_status_code="ERROR"),
            span("web", "2", trace="t2", otel_status_code="ERROR"),
            span("api", "3", trace="t3", otel_status_code="ERROR"),
            span("batch", "4", trace="t4"),
            span("batch", "5", trace="t5"),
            span("batch", "6", trace="t6"),
        ]
    )
    assert graph.entry_point == "web"


def test_no_failures_gives_no_failing_path_or_entry_point():
    graph = build_graph([span("frontend", "a"), span("cart", "b", parent="a")])
    assert graph.failing_path() == set()
    assert graph.entry_point is None


def test_empty_input_gives_an_empty_graph():
    graph = build_graph([])
    assert (graph.services, graph.edges, graph.failing_path()) == (set(), set(), set())


def test_window_keeps_spans_from_lookback_before_the_alert_up_to_the_alert():
    alert = datetime(2026, 10, 10, 10, 5, tzinfo=UTC)
    spans = [
        span("old", "1", start=alert - DEFAULT_LOOKBACK - timedelta(seconds=1)),
        span("edge", "2", start=alert - DEFAULT_LOOKBACK),
        span("in", "3", start=alert - timedelta(seconds=10)),
        span("at", "4", start=alert),
        span("after", "5", start=alert + timedelta(seconds=1)),
    ]
    kept = spans_in_window(spans, alert, DEFAULT_LOOKBACK)
    assert [s.service for s in kept] == ["edge", "in", "at"]


def test_window_without_alert_time_keeps_every_span():
    spans = [span("cart", "1")]
    assert spans_in_window(spans, None, DEFAULT_LOOKBACK) == spans


def test_window_rejects_mixed_time_zones():
    naive = span("cart", "1", start="2026-10-10T10:04:00")
    with pytest.raises(IngestError, match="time zone"):
        spans_in_window([naive], datetime(2026, 10, 10, 10, 5, tzinfo=UTC), DEFAULT_LOOKBACK)
