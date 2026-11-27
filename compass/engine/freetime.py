"""Busy blocks and free gaps for one day. The planner and the warnings both use this.

A day is `config.day_window` on that date, in `config.tz`. Busy time is:
- events that overlap the window, clipped to it. Events that span midnight count on both days.
  Free events (`busy=False`) never block time. All-day events count only if marked busy, and
  then block the whole window.
- protected time from config on its weekdays.

Overlapping busy blocks are merged into one. Everything returned is in `config.tz`.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from ..config import Config
from ..models import Block, Event

_WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def day_window(day: date, config: Config) -> tuple[datetime, datetime]:
    tz = config.tz
    return (datetime.combine(day, config.day_window.start, tzinfo=tz),
            datetime.combine(day, config.day_window.end, tzinfo=tz))


def _local(day: date, t: time, config: Config) -> datetime:
    return datetime.combine(day, t, tzinfo=config.tz)


def _minutes(start: datetime, end: datetime) -> int:
    # Subtract as timestamps: same-tzinfo subtraction in Python ignores DST changes.
    return int((end.timestamp() - start.timestamp()) // 60)


def busy_blocks(day: date, events: list[Event], config: Config) -> list[Block]:
    win_start, win_end = day_window(day, config)
    tz = config.tz
    raw: list[Block] = []

    for e in events:
        if not e.busy:
            continue
        if e.all_day:
            # All-day events cover local dates [start, end), end exclusive as in Google Calendar,
            # and always at least their start date. Compare dates, not instants.
            first, end_date = e.start.astimezone(tz).date(), e.end.astimezone(tz).date()
            if first <= day < max(end_date, first + timedelta(days=1)):
                raw.append(Block(start=win_start, end=win_end, kind=e.kind, title=e.title))
            continue
        start, end = max(e.start.astimezone(tz), win_start), min(e.end.astimezone(tz), win_end)
        if start < end:
            raw.append(Block(start=start, end=end, kind=e.kind, title=e.title))

    weekday = _WEEKDAYS[day.weekday()]
    for p in config.protected:
        if weekday in p.days:
            start = max(_local(day, p.start, config), win_start)
            end = min(_local(day, p.end, config), win_end)
            if start < end:
                raw.append(Block(start=start, end=end, kind="protected", title=p.title))

    return _merge(raw)


def _merge(blocks: list[Block]) -> list[Block]:
    """Merge blocks that overlap (touching blocks stay separate). A merged block is `fixed` if any
    part is a real event, and its title joins the parts in start order."""
    merged: list[Block] = []
    for b in sorted(blocks, key=lambda b: (b.start, b.end, b.title)):
        last = merged[-1] if merged else None
        if last and b.start < last.end:
            merged[-1] = Block(
                start=last.start, end=max(last.end, b.end),
                kind="fixed" if "fixed" in (last.kind, b.kind) else last.kind,
                title=last.title if b.title in last.title.split(" + ") else f"{last.title} + {b.title}",
            )
        else:
            merged.append(b)
    return merged


def free_gaps(day: date, events: list[Event], config: Config,
              not_before: datetime | None = None) -> list[tuple[datetime, datetime]]:
    """The day window minus busy blocks, in order. `not_before` drops time before that moment."""
    win_start, win_end = day_window(day, config)
    cursor = win_start
    if not_before is not None:
        cursor = max(cursor, not_before.astimezone(config.tz))
    gaps: list[tuple[datetime, datetime]] = []
    for b in busy_blocks(day, events, config):
        if b.start > cursor:
            gaps.append((cursor, min(b.start, win_end)))
        cursor = max(cursor, b.end)
    if cursor < win_end:
        gaps.append((cursor, win_end))
    return [(s, e) for s, e in gaps if s < e]


def free_minutes(day: date, events: list[Event], config: Config,
                 not_before: datetime | None = None) -> int:
    return sum(_minutes(s, e) for s, e in free_gaps(day, events, config, not_before))
