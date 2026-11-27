"""Spot trouble in the next `days` days before it happens. Messages are built by code.

Usable time on a day is its free minutes (from `now` onward, for today), capped at
`daily_cap_minutes`. Open work means tasks that aren't submitted or missing and have minutes left.

- **overdue:** past due and not submitted (missing tasks excluded: they may have been removed).
- **missing:** the last merge marked the task missing.
- **cannot_finish:** one task's remaining minutes exceed all the usable time between now and its
  due time. Tasks due after the horizon are skipped.
- **overloaded_day:** each open task's remaining minutes are spread evenly over the days before its
  due date (all on today if it's due today or overdue), the same pacing the planner uses. A day is
  overloaded when the work paced to be done by the end of it is more than the usable time up to
  it. Earlier slack counts, so a free Monday can absorb a busy Tuesday. One warning is given per
  run of overloaded days, dated on its first day, with the largest shortfall in the run.

Sorted by date, then kind (in the order of KINDS), then task ID.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel

from ..config import Config
from ..models import Event, Task
from .freetime import free_gaps

Kind = Literal["overdue", "missing", "cannot_finish", "overloaded_day"]
KINDS: tuple[Kind, ...] = ("overdue", "missing", "cannot_finish", "overloaded_day")


class Warning(BaseModel):  # noqa: A001 - the name the plan uses; shadows the builtin only here
    kind: Kind
    date: date
    task_id: str | None = None
    message: str


def _minutes(start: datetime, end: datetime) -> int:
    return max(0, int((end.timestamp() - start.timestamp()) // 60))


def _usable(day: date, events: list[Event], config: Config, now: datetime,
            until: datetime | None = None) -> int:
    """Free minutes on `day` from `now`, optionally only before `until`, capped at the daily cap."""
    total = 0
    for start, end in free_gaps(day, events, config, not_before=now):
        if until is not None:
            end = min(end, until)
        total += _minutes(start, end)
    return min(total, config.planner.daily_cap_minutes)


def _hours(minutes: float) -> str:
    if minutes < 60:
        return f"{int(round(minutes))} min"
    hours = round(minutes / 60 * 2) / 2
    return f"{hours:g} h"


def _day(d: date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def _when(dt: datetime, config: Config) -> str:
    local = dt.astimezone(config.tz)
    return f"{_day(local.date())} {local:%H:%M}"


def _label(task: Task) -> str:
    return f"{task.title} ({task.course})" if task.course else task.title


def _work_days(task: Task, today: date, config: Config) -> int:
    """Days the task's remaining minutes are spread over, starting today."""
    if task.due is None:
        return 0
    return max((task.due.astimezone(config.tz).date() - today).days, 1)


def check(tasks: list[Task], events: list[Event], config: Config, now: datetime,
          days: int = 14) -> list[Warning]:
    today = now.astimezone(config.tz).date()
    horizon = [today + timedelta(days=i) for i in range(days)]
    usable = {d: _usable(d, events, config, now) for d in horizon}
    warnings: list[Warning] = []

    for t in tasks:
        if t.missing:
            when = t.due.astimezone(config.tz).date() if t.due else today
            warnings.append(Warning(
                kind="missing", date=when, task_id=t.id,
                message=f"{_label(t)} wasn't in the last {t.source} fetch. "
                        "Check whether it was removed or moved."))
        elif not t.submitted and t.due is not None and t.due <= now:
            warnings.append(Warning(
                kind="overdue", date=t.due.astimezone(config.tz).date(), task_id=t.id,
                message=f"{_label(t)} was due {_when(t.due, config)} and isn't submitted."))

    open_tasks = [t for t in tasks
                  if not t.submitted and not t.missing and t.remaining_minutes > 0]

    for t in open_tasks:
        if t.due is None or t.due <= now:
            continue
        due_day = t.due.astimezone(config.tz).date()
        if due_day not in usable:
            continue
        free = sum(usable[d] for d in horizon if d < due_day)
        free += _usable(due_day, events, config, now, until=t.due.astimezone(config.tz))
        if t.remaining_minutes > free:
            warnings.append(Warning(
                kind="cannot_finish", date=due_day, task_id=t.id,
                message=f"{_label(t)} needs about {_hours(t.remaining_minutes)} but there's only "
                        f"about {_hours(free)} free before it's due {_when(t.due, config)}."))

    # Paced work per day: each dated task's minutes spread over its work days from today.
    paced = {d: 0.0 for d in horizon}
    for t in open_tasks:
        n = _work_days(t, today, config)
        for i in range(min(n, days)):
            paced[horizon[i]] += t.remaining_minutes / n

    needed = capacity = 0.0
    run_start: date | None = None
    worst = 0.0
    for d in horizon + [None]:
        if d is not None:
            needed += paced[d]
            capacity += usable[d]
            short = needed - capacity
        if d is not None and short > 0.5:  # ignore rounding dust
            run_start = run_start or d
            worst = max(worst, short)
            continue
        if run_start is not None:
            warnings.append(Warning(
                kind="overloaded_day", date=run_start,
                message=f"From {_day(run_start)}, the work due needs about {_hours(worst)} more "
                        "than your free time. Start something early or move a commitment."))
            run_start, worst = None, 0.0

    order = {k: i for i, k in enumerate(KINDS)}
    return sorted(warnings, key=lambda w: (w.date, order[w.kind], w.task_id or ""))
