from datetime import datetime
from pathlib import Path

from argus.context.service import build_context
from argus.contracts import AnomalySignal, CompressedTelemetry, SemanticContext, TelemetryBatch
from argus.diagnosis.loop.context_adapter import adapt, failing_path
from argus.diagnosis.loop.generator import RuleGenerator
from argus.orchestration.service import compress

SCENARIO_01 = Path(__file__).resolve().parents[3] / "data" / "fixtures" / "m1" / "scenario_01"
T = datetime(2026, 10, 10, 10, 4, 30)


def weights(diag):
    return {c.service: c.weight for c in diag.candidates}


def signal(service, name="log_error"):
    return AnomalySignal(service=service, source="log", name=name, timestamp=T, evidence="x")


def test_scenario_01_after_m1_f1_puts_cart_first_and_frontend_in():
    batch = TelemetryBatch.model_validate_json((SCENARIO_01 / "telemetry.json").read_text(encoding="utf-8"))
    # The real M4 -> M1 path, Stage 1 only: no graph, so the adapter falls back to signal counts.
    diag = adapt(build_context(compress(batch), strategy="stage1"), "online-boutique")

    assert diag.namespace == "online-boutique"
    assert diag.candidates[0].service == "cart"  # most kept signals (5xx + two log errors)
    assert diag.candidates[0].weight == 1.5
    assert weights(diag)["frontend"] == 1.0
    assert diag.failing_path == []  # stage1 sends no graph
    assert any("CART_ADDR" in s for s in diag.symptoms)


def test_scenario_01_after_m1_f2_uses_the_failing_path():
    batch = TelemetryBatch.model_validate_json((SCENARIO_01 / "telemetry.json").read_text(encoding="utf-8"))
    diag = adapt(build_context(compress(batch)), "online-boutique")  # M1's default, failing_path

    assert diag.failing_path == ["frontend", "cart"]
    assert weights(diag) == {"cart": 1.5, "frontend": 1.0}  # cart is the deepest failing service
    assert any("CART_ADDR" in s for s in diag.symptoms)


def test_graph_mode_weights_deepest_failing_service_highest():
    ctx = SemanticContext(
        services=["frontend", "checkout", "cart", "redis-cart", "product-catalog"],
        dependencies=[
            ("frontend", "checkout"),
            ("checkout", "cart"),
            ("cart", "redis-cart"),
            ("frontend", "product-catalog"),
        ],
        failing_services=["cart", "frontend", "checkout"],
        entry_point="frontend",
    )
    diag = adapt(ctx, "ns")

    assert diag.failing_path == ["frontend", "checkout", "cart"]
    assert weights(diag) == {
        "cart": 1.5,
        "frontend": 1.0,
        "checkout": 1.0,
        "redis-cart": 0.5,
        "product-catalog": 0.5,
    }
    assert [c.service for c in diag.candidates][:3] == ["cart", "frontend", "checkout"]


def test_healthy_upstream_caller_stays_on_the_failing_path():
    # The gateway catches cart's error and reports none itself, but the failing requests went through it.
    ctx = SemanticContext(
        services=["gateway", "cart"],
        dependencies=[("gateway", "cart")],
        failing_services=["cart"],
        entry_point="gateway",
    )
    diag = adapt(ctx, "ns")

    assert diag.failing_path == ["gateway", "cart"]
    assert weights(diag) == {"cart": 1.5, "gateway": 1.0}


def test_upstream_walk_stops_at_the_entry_point_and_skips_unrelated_callers():
    ctx = SemanticContext(
        dependencies=[
            ("lb", "frontend"),  # above the entry point
            ("frontend", "checkout"),
            ("checkout", "cart"),
            ("batch-job", "cart"),  # calls cart, but not on the route the failing requests took
        ],
        failing_services=["cart"],
        entry_point="frontend",
    )
    diag = adapt(ctx, "ns")

    assert diag.failing_path == ["frontend", "checkout", "cart"]
    assert weights(diag) == {"cart": 1.5, "frontend": 1.0, "checkout": 1.0, "lb": 0.5, "batch-job": 0.5}


def test_failing_caller_above_a_healthy_hop_is_not_deepest():
    # frontend fails only because cart does; the healthy gateway between them must not hide that.
    ctx = SemanticContext(
        dependencies=[("frontend", "gateway"), ("gateway", "cart")],
        failing_services=["frontend", "cart"],
        entry_point="frontend",
    )
    diag = adapt(ctx, "ns")

    assert diag.failing_path == ["frontend", "gateway", "cart"]
    assert weights(diag) == {"cart": 1.5, "frontend": 1.0, "gateway": 1.0}
    assert diag.candidates[0].service == "cart"
    assert {h.component for h in RuleGenerator().draft(diag, k=3)} == {"cart"}  # first round tests cart


def test_without_entry_point_healthy_callers_are_walked_to_the_top():
    ctx = SemanticContext(dependencies=[("a", "b"), ("b", "c")], failing_services=["c"])
    assert failing_path(ctx) == ["a", "b", "c"]
    assert weights(adapt(ctx, "ns")) == {"c": 1.5, "a": 1.0, "b": 1.0}


def test_failing_path_without_entry_point_starts_from_the_uncalled_service():
    ctx = SemanticContext(dependencies=[("a", "b"), ("b", "c")], failing_services=["c", "b", "a"])
    assert failing_path(ctx) == ["a", "b", "c"]


def test_failing_cycle_still_gives_one_deepest_service():
    ctx = SemanticContext(dependencies=[("a", "b"), ("b", "a")], failing_services=["a", "b"], entry_point="a")
    diag = adapt(ctx, "ns")
    assert diag.failing_path == ["a", "b"]
    assert weights(diag) == {"b": 1.5, "a": 1.0}


def test_failing_services_without_edges_fall_back_to_signal_mode():
    ctx = SemanticContext(failing_services=["cart"], kept_signals=[signal("frontend")])
    assert weights(adapt(ctx, "ns")) == {"frontend": 1.5, "cart": 1.0}


def test_tied_signal_counts_all_get_the_top_weight():
    ctx = SemanticContext(kept_signals=[signal("a"), signal("b")])
    assert weights(adapt(ctx, "ns")) == {"a": 1.5, "b": 1.5}


def test_symptoms_keep_order_and_drop_repeats():
    ctx = SemanticContext(symptoms=["cart: 5xx"], anomalies=["cart: 5xx", "frontend: 5xx"])
    assert adapt(ctx, "ns").symptoms == ["cart: 5xx", "frontend: 5xx"]


def test_empty_context_gives_no_candidates():
    diag = adapt(SemanticContext(), "ns")
    assert diag.candidates == [] and diag.symptoms == [] and diag.failing_path == []


def test_m1_ingest_error_reaches_m2_through_notes():
    bad = CompressedTelemetry(content="kind\tservice\nnot-json\tcart\n", original_size=0, compressed_size=0)
    diag = adapt(build_context(bad), "ns")
    assert diag.candidates == []
    assert diag.notes.startswith("M1 could not read the telemetry")
