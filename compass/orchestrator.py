"""Workflows: glue between the store and the pure engine. Step 1.9 adds `morning()` here."""

from __future__ import annotations

from .engine.estimate import auto_estimates
from .store import Store


def apply_estimates(store: Store) -> int:
    """Set the automatic estimate for every task without a manual override. Returns how many."""
    estimates = auto_estimates(store.get_tasks(), store.get_overrides())
    for task_id, minutes in estimates.items():
        store.set_auto_estimate(task_id, minutes)
    return len(estimates)
