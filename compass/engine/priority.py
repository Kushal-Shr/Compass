"""Rank tasks so the planner knows what to schedule first.

The score is a sum of four parts. Higher means more urgent.

1. **Urgency** halves for every day until the due date: URGENCY_WEIGHT at the deadline,
   half of it 24 hours out, a quarter at 48 hours, under 1% a week out. Anything due within
   24 hours scores over URGENCY_WEIGHT / 2, which the other parts rarely reach for later tasks.
2. **Overdue**: a task past due and not submitted gets OVERDUE_BOOST, so it ranks first.
3. **Points** add a small, slowly growing boost: POINTS_WEIGHT * ln(1 + points). Between two
   tasks due at the same time, the one worth more ranks higher.
4. **Load**: remaining work as a share of the time left until the due date, capped at
   LOAD_CAP, times LOAD_WEIGHT. Ten hours of work due in a day scores higher than one hour.

Tasks without a due date get no urgency or load. `rank` always puts them after every dated
task, ordered among themselves by points.
"""

from __future__ import annotations

import math
from datetime import datetime

from ..models import Task

URGENCY_WEIGHT = 100.0
URGENCY_HALF_LIFE_HOURS = 24.0
OVERDUE_BOOST = 1000.0
POINTS_WEIGHT = 2.0
LOAD_WEIGHT = 50.0
LOAD_CAP = 1.0  # needing all of the time left (or more) counts the same


def _hours_left(task: Task, now: datetime) -> float | None:
    return None if task.due is None else (task.due - now).total_seconds() / 3600


def score(task: Task, now: datetime) -> float:
    hours = _hours_left(task, now)
    total = POINTS_WEIGHT * math.log1p(max(task.points, 0))
    if hours is None:
        return total
    total += URGENCY_WEIGHT * 0.5 ** (max(hours, 0) / URGENCY_HALF_LIFE_HOURS)
    if hours <= 0:
        load = LOAD_CAP
        if not task.submitted:
            total += OVERDUE_BOOST
    else:
        load = min(task.remaining_minutes / (hours * 60), LOAD_CAP)
    return total + LOAD_WEIGHT * load


def rank(tasks: list[Task], now: datetime) -> list[Task]:
    """Open tasks with work left, most urgent first.

    Drops submitted tasks, missing tasks and tasks with no remaining minutes (so estimates must be
    applied first). Undated tasks come after all dated ones. Ties break by due date, then ID,
    so the order is stable.
    """
    open_tasks = [t for t in tasks if not t.submitted and not t.missing and t.remaining_minutes > 0]
    return sorted(open_tasks, key=lambda t: (
        t.due is None,
        -score(t, now),
        t.due or now,
        t.id,
    ))
