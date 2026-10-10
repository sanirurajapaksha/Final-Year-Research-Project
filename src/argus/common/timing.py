import time
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def stage_timer(timings: dict[str, float], stage: str) -> Iterator[None]:
    """Record how long a block took, in milliseconds, under `timings[stage]`.

    Use one timer per pipeline stage so latency can be reported per stage, not just end to end.
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        timings[stage] = (time.perf_counter() - start) * 1000.0
