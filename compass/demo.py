"""Fake but realistic data, so every feature works with `--demo` and no accounts.

Everything is fixed relative to `DEMO_TODAY`, so each call returns identical output.
Course and assignment names are generic, never real ones.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import Event, Task

DEMO_TZ = ZoneInfo("America/Chicago")
DEMO_TODAY = datetime(2026, 11, 30, 7, 0, tzinfo=DEMO_TZ)  # a Monday
DEMO_DAYS = 14

CS = "CS 201 Data Structures"
MATH = "MATH 220 Linear Algebra"
HIST = "HIST 110 World History"
BIO = "BIO 150 Introductory Biology"


def _at(day_offset: int, hhmm: str) -> datetime:
    """Wall-clock time in DEMO_TZ, `day_offset` days after DEMO_TODAY."""
    hour, minute = map(int, hhmm.split(":"))
    day = DEMO_TODAY.date() + timedelta(days=day_offset)
    return datetime.combine(day, time(hour, minute), tzinfo=DEMO_TZ)


# (id, course, title, due day offset, due time, points, submitted)
_TASKS = [
    ("demo:101", MATH, "Problem Set 7", 0, "23:59", 20, False),                      # due tonight
    ("demo:102", HIST, "Discussion Post: Week 13", -1, "23:59", 10, False),          # overdue
    ("demo:103", CS, "Lab 6: Hash Tables", 2, "23:59", 30, True),                    # already submitted
    ("demo:104", BIO, "Reading: Chapter 14", 1, "13:00", 5, False),
    ("demo:105", HIST, "Reading: Primary Sources Packet", 3, "09:30", 5, False),
    ("demo:106", MATH, "Quiz 8: Eigenvalues", 4, "11:00", 15, False),
    ("demo:107", BIO, "Lab Report 9: Enzyme Activity", 4, "23:59", 40, False),
    ("demo:108", HIST, "Essay: Causes of Industrialization", 7, "23:59", 100, False),
    ("demo:109", MATH, "Problem Set 8", 7, "23:59", 20, False),
    ("demo:110", CS, "Final Project: Route Planner", 11, "23:59", 200, False),       # big project
]


def demo_tasks() -> list[Task]:
    return [
        Task(id=task_id, title=title, source="demo", course=course,
             due=_at(offset, hhmm), points=points, submitted=submitted)
        for task_id, course, title, offset, hhmm, points, submitted in _TASKS
    ]


# (course code, title, weekdays (0 = Mon), start, end)
_CLASSES = [
    ("cs201", f"{CS} lecture", (0, 2, 4), "09:00", "09:50"),
    ("math220", f"{MATH} lecture", (0, 2, 4), "11:00", "11:50"),
    ("hist110", f"{HIST} lecture", (1, 3), "09:30", "10:45"),
    ("bio150", f"{BIO} lecture", (1, 3), "13:00", "14:15"),
]

# (id, title, day offset, start, end)
_ONE_OFFS = [
    ("demo:event:study-group", "CS 201 study group", 1, "17:30", "18:30"),  # overlaps dinner
    ("demo:event:dentist", "Dentist appointment", 3, "15:00", "16:00"),
    ("demo:event:shift", "Campus job shift", 5, "10:00", "14:00"),
]


def demo_events() -> list[Event]:
    events: list[Event] = []
    for offset in range(DEMO_DAYS):
        day: date = DEMO_TODAY.date() + timedelta(days=offset)
        for code, title, weekdays, start, end in _CLASSES:
            if day.weekday() in weekdays:
                events.append(Event(id=f"demo:class:{code}:{day.isoformat()}", title=title,
                                    start=_at(offset, start), end=_at(offset, end)))
    for event_id, title, offset, start, end in _ONE_OFFS:
        events.append(Event(id=event_id, title=title, start=_at(offset, start), end=_at(offset, end)))
    return sorted(events, key=lambda e: (e.start, e.id))
