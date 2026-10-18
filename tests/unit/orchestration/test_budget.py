from dataclasses import FrozenInstanceError

import pytest

from argus.orchestration.budget import BudgetExceeded, EstimatedBudget


def test_reservation_charge_and_release_preserve_the_budget():
    ledger = EstimatedBudget(10, "test credits")
    initial = ledger.reserve(4)
    assert ledger.snapshot().available_units == 6
    assert ledger.snapshot().spent_units == 0
    before = ledger.snapshot()
    with pytest.raises(BudgetExceeded):
        ledger.reserve(7)
    assert ledger.snapshot() == before
    ledger.charge(initial)
    assert ledger.snapshot().spent_units == 4
    unused = ledger.reserve(6)
    assert ledger.snapshot().available_units == 0
    ledger.release(unused)
    assert ledger.snapshot().available_units == 6
    assert ledger.snapshot().reserved_units == 0


@pytest.mark.parametrize("amount", [-1, True, 1.5, "1"])
def test_invalid_amounts_rejected_without_changing_state(amount):
    with pytest.raises(ValueError):
        EstimatedBudget(amount, "credits")
    ledger = EstimatedBudget(10, "credits")
    before = ledger.snapshot()
    with pytest.raises(ValueError):
        ledger.reserve(amount)
    assert ledger.snapshot() == before


@pytest.mark.parametrize("unit", ["", " \t", None, 1])
def test_unit_must_be_explicit(unit):
    with pytest.raises(ValueError):
        EstimatedBudget(10, unit)


@pytest.mark.parametrize("consumed_by", ["charge", "release"])
def test_reservations_are_single_use_and_cannot_cross_ledgers(consumed_by):
    ledger = EstimatedBudget(10, "credits")
    other = EstimatedBudget(10, "credits")
    token = ledger.reserve(3)
    with pytest.raises(ValueError):
        other.charge(token)
    getattr(ledger, consumed_by)(token)
    before = ledger.snapshot()
    for operation in (ledger.charge, ledger.release):
        with pytest.raises(ValueError):
            operation(token)
        assert ledger.snapshot() == before


def test_zero_reservations_and_immutable_snapshots():
    ledger = EstimatedBudget(0, "credits")
    token = ledger.reserve(0)
    ledger.charge(token)
    assert ledger.snapshot().spent_units == ledger.snapshot().available_units == 0
    with pytest.raises(FrozenInstanceError):
        ledger.snapshot().spent_units = 100
