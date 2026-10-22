import pytest

FIXTURES = ["cart_addr", "chain4", "redis_down", "misleading"]


@pytest.mark.parametrize("name", FIXTURES)
def test_context_fixture_is_a_valid_m1_context_with_a_truth(m2_context, name):
    ctx, truth = m2_context(name)

    assert ctx.failing_services and ctx.dependencies and ctx.entry_point  # graph mode, as M1 F2 sends
    assert ctx.kept_signals
    assert {"component", "layer", "fault"} <= truth.keys()
