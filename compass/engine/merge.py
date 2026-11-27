"""Write fetched data to the store and collect what changed.

The one engine module that takes a `Store`, because merging is a store operation.
The caller must not merge a source whose fetch errored (D3): that would mark every task missing.
"""

from __future__ import annotations

from datetime import datetime

from ..models import Change, Event, Task
from ..store import Store


def merge_tasks(store: Store, source: str, tasks: list[Task], now: datetime,
                window: tuple[datetime, datetime]) -> list[Change]:
    """Upsert `tasks` from `source`, then mark stored tasks from that source missing if absent.

    `window` is the (start, end) range the source fetched. A stored task is marked missing only
    if it wasn't fetched, isn't submitted, isn't past due, and its due date is inside the window
    (D3). Undated tasks are never marked missing, since no window can say they should be there.
    """
    wrong = [t.id for t in tasks if t.source != source]
    if wrong:
        raise ValueError(f"tasks from another source passed to merge_tasks({source!r}): {wrong}")
    start, end = window

    changes: list[Change] = []
    for task in tasks:
        changes += store.upsert_task(task, now)

    fetched = {t.id for t in tasks}
    for stored in store.get_tasks(source=source):
        if (stored.id in fetched or stored.missing or stored.submitted
                or stored.due is None or stored.due < now
                or not start <= stored.due <= end):
            continue
        change = store.mark_missing(stored.id, now)
        if change:
            changes.append(change)
    return changes


def merge_events(store: Store, events: list[Event], source: str | None = None) -> None:
    """Replace stored events: only `source`'s when given (IDs `source:...`), otherwise all."""
    store.replace_events(events, source=source)
