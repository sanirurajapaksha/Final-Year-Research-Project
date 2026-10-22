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


# --- hop scheme -------------------------------------------------------------------------------


def roles(diag):
    return {c.service: (c.role, c.hops) for c in diag.candidates}


def test_hop_scheme_grades_the_chain_by_distance_from_the_origin(m2_context):
    ctx, _ = m2_context("chain4")
    diag = adapt(ctx, "ns", scheme="hop")

    assert weights(diag) == {
        "cart": 1.5,  # origin
        "checkout": 1.0,  # 1 hop up
        "redis-cart": 1.0,  # quiet dependency: cart calls it, it reports nothing
        "frontend": 0.7,  # 2 hops up
        "product-catalog": 0.5,  # off the failing path
    }
    assert roles(diag) == {
        "cart": ("origin", 0),
        "checkout": ("upstream", 1),
        "redis-cart": ("quiet-dependency", 1),
        "frontend": ("upstream", 2),
        "product-catalog": ("other", None),
    }


def test_almanac_scheme_keeps_the_three_levels_and_adds_roles(m2_context):
    ctx, _ = m2_context("chain4")
    diag = adapt(ctx, "ns")  # the default scheme

    assert weights(diag) == {
        "cart": 1.5,
        "frontend": 1.0,
        "checkout": 1.0,
        "redis-cart": 0.5,
        "product-catalog": 0.5,
    }
    assert roles(diag)["redis-cart"] == ("quiet-dependency", 1)  # role is shown, weight is unchanged


def test_three_or_more_hops_up_get_the_far_weight():
    ctx = SemanticContext(
        dependencies=[("lb", "web"), ("web", "api"), ("api", "orders"), ("orders", "db")],
        failing_services=["lb", "web", "api", "orders", "db"],
        entry_point="lb",
    )
    assert weights(adapt(ctx, "ns", scheme="hop")) == {
        "db": 1.5,
        "orders": 1.0,
        "api": 0.7,
        "web": 0.5,
        "lb": 0.5,
    }


def test_service_named_only_in_the_origins_log_becomes_a_quiet_dependency(m2_context):
    ctx, _ = m2_context("redis_down")  # M1 knows frontend and cart; redis-cart is only in cart's error
    diag = adapt(ctx, "ns", scheme="hop")

    assert weights(diag) == {"cart": 1.5, "frontend": 1.0, "redis-cart": 1.0}
    assert roles(diag)["redis-cart"] == ("quiet-dependency", 1)


def test_your_m1_log_adds_redis_from_carts_error(m2_context):
    ctx, _ = m2_context("cart_addr")  # "failed to connect to redis: CART_ADDR ..."
    assert weights(adapt(ctx, "ns", scheme="hop")) == {"cart": 1.5, "frontend": 1.0, "redis": 1.0}
    assert "redis" not in weights(adapt(ctx, "ns"))  # almanac never reads names out of log text


def test_short_name_in_a_log_resolves_to_the_known_service():
    ctx = SemanticContext(
        services=["frontend", "cart", "redis-cart"],
        dependencies=[("frontend", "cart")],
        failing_services=["frontend", "cart"],
        entry_point="frontend",
        kept_signals=[
            AnomalySignal(
                service="cart",
                source="log",
                name="log_error",
                timestamp=T,
                evidence="failed to connect to redis: connection refused",
            ),
        ],
    )
    diag = adapt(ctx, "ns", scheme="hop")
    assert weights(diag) == {"cart": 1.5, "frontend": 1.0, "redis-cart": 1.0}


def test_common_words_and_upstream_logs_add_no_service():
    ctx = SemanticContext(
        dependencies=[("frontend", "cart")],
        failing_services=["frontend", "cart"],
        entry_point="frontend",
        kept_signals=[
            AnomalySignal(
                service="cart",
                source="log",
                name="log_error",
                timestamp=T,
                evidence="failed to connect to the server",
            ),
            # frontend is not the origin: what it names is on the path or past it, never a quiet dependency
            AnomalySignal(
                service="frontend",
                source="log",
                name="log_error",
                timestamp=T,
                evidence="dial tcp: lookup payments: no such host",
            ),
        ],
    )
    assert weights(adapt(ctx, "ns", scheme="hop")) == {"cart": 1.5, "frontend": 1.0}


def test_signal_mode_is_the_same_in_both_schemes_and_marks_the_top():
    ctx = SemanticContext(kept_signals=[signal("a"), signal("a"), signal("b")], services=["c"])
    assert adapt(ctx, "ns", scheme="hop") == adapt(ctx, "ns")
    assert roles(adapt(ctx, "ns")) == {
        "a": ("top-signals", None),
        "b": ("has-signals", None),
        "c": ("other", None),
    }
