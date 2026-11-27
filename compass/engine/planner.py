"""Fill one day's free time with study blocks.

How it works:
1. Free gaps come from `free_gaps`, never before `now`, with each gap starting on a 5-minute mark.
2. Order: tasks due tonight first (in rank order), then everything else in `rank` order.
3. Each task asks for a share of today:
   - due tonight or overdue: all its remaining minutes
   - due later: remaining minutes spread over the days before the due date
     (due Fri, planning Mon: a quarter today, for Mon-Thu, leaving the due day as a buffer)
   - undated: one max-length block
   A share is rounded up to 5 minutes and is at least one minimum block.
4. Each task's share is placed in the earliest gaps that fit, as blocks between
   `min_block_minutes` and `max_block_minutes`, each followed by a break (shortened if the gap
   ends first). A block for a dated task always ends by its due time. Gaps too short for a
   minimum block stay empty.
5. Study time stops at `daily_cap_minutes`. Tasks that got no time go in `unplaced`.
6. The plan lists busy blocks, study blocks and breaks together, sorted by start.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta

from ..config import Config
from ..models import Block, DayPlan, Event, Task
from .freetime import busy_blocks, free_gaps
from .priority import rank

STEP_MINUTES = 5


def _ceil5(minutes: float) -> int:
    return int(math.ceil(minutes / STEP_MINUTES)) * STEP_MINUTES


def _round_up_to_step(t: datetime) -> datetime:
    extra = (t.minute % STEP_MINUTES) * 60 + t.second + t.microsecond / 1e6
    return t if extra == 0 else t + timedelta(seconds=STEP_MINUTES * 60 - extra)


def _minutes(start: datetime, end: datetime) -> int:
    return int((end.timestamp() - start.timestamp()) // 60)


def _due_tonight(task: Task, day: date, config: Config) -> bool:
    return task.due is not None and task.due.astimezone(config.tz).date() == day


def daily_share(task: Task, day: date, config: Config) -> int:
    """Minutes this task asks for on `day` (before fitting into gaps and the cap)."""
    remaining = task.remaining_minutes
    if task.due is None:
        share = config.planner.max_block_minutes
    else:
        days_left = (task.due.astimezone(config.tz).date() - day).days
        share = remaining if days_left <= 1 else remaining / days_left
    share = max(_ceil5(min(share, remaining)), config.planner.min_block_minutes)
    return share


def _split(want: int, room: int, config: Config) -> int:
    """Length of the next block: at most `room`, between min and max, never leaving a remainder
    shorter than a minimum block when a different split would avoid it."""
    lo, hi = config.planner.min_block_minutes, config.planner.max_block_minutes
    length = min(want, hi, room)
    left = want - length
    if 0 < left < lo and length - (lo - left) >= lo:
        length -= lo - left
    return length if length >= lo else 0


def plan_day(day: date, tasks: list[Task], events: list[Event], config: Config,
             now: datetime) -> DayPlan:
    p = config.planner
    gaps = [[_round_up_to_step(s), e] for s, e in free_gaps(day, events, config, not_before=now)]
    gaps = [g for g in gaps if g[0] < g[1]]

    ranked = rank(tasks, now)
    ordered = ([t for t in ranked if _due_tonight(t, day, config)]
               + [t for t in ranked if not _due_tonight(t, day, config)])

    study: list[Block] = []
    breaks: list[Block] = []
    cap_left = p.daily_cap_minutes
    unplaced: list[str] = []

    for task in ordered:
        left = min(daily_share(task, day, config), cap_left)  # never more than the cap allows
        deadline = task.due.astimezone(config.tz) if task.due and task.due > now else None
        placed = 0
        for gap in gaps:
            while left >= p.min_block_minutes:
                end_limit = min(gap[1], deadline) if deadline else gap[1]
                length = _split(left, _minutes(gap[0], end_limit), config)
                if length == 0:
                    break  # this gap is full or past the deadline: try the next one
                block_end = gap[0] + timedelta(minutes=length)
                study.append(Block(start=gap[0], end=block_end, kind="study", title=task.title,
                                   task_id=task.id))
                placed += length
                left -= length
                cap_left -= length
                rest = min(p.break_minutes, _minutes(block_end, gap[1]))
                if rest > 0:
                    breaks.append(Block(start=block_end, end=block_end + timedelta(minutes=rest),
                                        kind="break", title="Break"))
                gap[0] = block_end + timedelta(minutes=rest)
        if placed == 0:
            unplaced.append(task.id)

    blocks = busy_blocks(day, events, config) + study + breaks
    blocks.sort(key=lambda b: (b.start, b.end))
    return DayPlan(date=day, blocks=blocks, unplaced=unplaced)
