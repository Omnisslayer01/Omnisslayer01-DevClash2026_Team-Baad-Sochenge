"""
Simulated upstream latency and flaky behavior (no paid APIs).
"""

from __future__ import annotations

import random
import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")


def simulated_delay_ms(min_ms: int = 120, max_ms: int = 480) -> None:
    """Mimics network + government registry round-trip."""
    time.sleep(random.uniform(min_ms, max_ms) / 1000.0)


def maybe_upstream_failure(failure_rate: float = 0.012) -> str | None:
    """
    Rare synthetic outage. Returns error message or None if OK.
    Keeps the demo from looking 'too perfect'.
    """
    if random.random() < failure_rate:
        return (
            "Upstream registry temporarily unavailable (simulated). "
            "Retry after a short delay."
        )
    return None


def maybe_random_not_found(not_found_rate: float = 0.008) -> bool:
    """Rare false negative to mimic stale cache / propagation delay."""
    return random.random() < not_found_rate


def with_realism(
    fn: Callable[[], T],
    *,
    min_ms: int = 120,
    max_ms: int = 480,
    failure_rate: float = 0.012,
) -> tuple[T | None, str | None]:
    """
    Run fn after delay; optionally short-circuit with synthetic outage.
    Returns (result, error_message).
    """
    simulated_delay_ms(min_ms, max_ms)
    err = maybe_upstream_failure(failure_rate)
    if err:
        return None, err
    return fn(), None
