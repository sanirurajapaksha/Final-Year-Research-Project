"""Sequential, in-memory accounting of estimated costs, not provider billing."""

from dataclasses import dataclass


class BudgetExceeded(ValueError):
    """The requested reservation exceeds the available estimated budget."""


@dataclass(frozen=True)
class BudgetSnapshot:
    limit_units: int
    spent_units: int
    reserved_units: int
    available_units: int
    cost_unit: str


class EstimatedBudget:
    """Retain one ledger across sequential batches in an incident.

    Charge the full estimate when dispatch starts, including failed attempts.
    This neither records actual usage nor guarantees a real provider spend cap.
    Concurrent use and durable accounting are outside this prototype's scope.
    """

    def __init__(self, limit_units: int, cost_unit: str):
        if type(limit_units) is not int or limit_units < 0:
            raise ValueError("limit_units must be a nonnegative integer")
        if not isinstance(cost_unit, str) or not cost_unit.strip():
            raise ValueError("cost_unit must be a nonempty string")
        self._limit = limit_units
        self._unit = cost_unit
        self._spent = 0
        self._reservations: dict[object, int] = {}

    def snapshot(self) -> BudgetSnapshot:
        reserved = sum(self._reservations.values())
        return BudgetSnapshot(
            self._limit, self._spent, reserved, self._limit - self._spent - reserved, self._unit
        )

    def reserve(self, amount: int) -> object:
        if type(amount) is not int or amount < 0:
            raise ValueError("reservation must be a nonnegative integer")
        if amount > self.snapshot().available_units:
            raise BudgetExceeded("insufficient unreserved estimated budget")
        token = object()
        self._reservations[token] = amount
        return token

    def charge(self, token: object) -> None:
        """Consume a reservation exactly once when an attempt starts."""
        if token not in self._reservations:
            raise ValueError("unknown or already consumed reservation")
        self._spent += self._reservations.pop(token)

    def release(self, token: object) -> None:
        """Release an unused reservation; started attempts are never refunded."""
        if token not in self._reservations:
            raise ValueError("unknown or already consumed reservation")
        del self._reservations[token]
