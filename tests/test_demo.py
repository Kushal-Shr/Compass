import statistics
from datetime import time, timedelta

from compass.demo import DEMO_TODAY, demo_events, demo_tasks

END = DEMO_TODAY + timedelta(days=14)
# Matches the Dinner block in config.yaml. Hardcoded so editing the config can't break demo tests.
DINNER = (time(18, 0), time(19, 0))


def _has(word: str) -> bool:
    return any(word in t.title.lower() for t in demo_tasks())


def test_deterministic():
    assert [t.model_dump() for t in demo_tasks()] == [t.model_dump() for t in demo_tasks()]
    assert [e.model_dump() for e in demo_events()] == [e.model_dump() for e in demo_events()]


def test_all_datetimes_aware():
    assert DEMO_TODAY.tzinfo is not None
    stamps = [t.due for t in demo_tasks()] + [d for e in demo_events() for d in (e.start, e.end)]
    assert all(d is not None and d.utcoffset() is not None for d in stamps)


def test_ids_and_shape():
    tasks, events = demo_tasks(), demo_events()
    assert 8 <= len(tasks) <= 12
    assert 3 <= len({t.course for t in tasks}) <= 4
    ids = [t.id for t in tasks] + [e.id for e in events]
    assert len(ids) == len(set(ids))
    assert all(i.startswith("demo:") for i in ids)
    assert all(e.start < e.end for e in events)
    assert all(DEMO_TODAY - timedelta(days=7) <= t.due <= END for t in tasks)


def test_required_task_cases():
    tasks = demo_tasks()
    assert any(t.due.date() == DEMO_TODAY.date() and t.due > DEMO_TODAY and not t.submitted
               for t in tasks), "due tonight"
    assert any(t.due < DEMO_TODAY and not t.submitted for t in tasks), "overdue, not submitted"
    assert any(t.submitted for t in tasks), "already submitted"
    median = statistics.median(t.points for t in tasks)
    assert any(t.points >= 5 * median and "project" in t.title.lower() for t in tasks), "big project"
    for word in ("essay", "quiz", "lab", "reading"):
        assert _has(word), word


def test_weekly_class_schedule():
    classes = [e for e in demo_events() if e.id.startswith("demo:class:")]
    assert all(DEMO_TODAY.date() <= e.start.date() < END.date() for e in classes)
    days_by_course: dict[str, set[int]] = {}
    for e in classes:
        days_by_course.setdefault(e.title, set()).add(e.start.weekday())
    patterns = set(map(frozenset, days_by_course.values()))
    assert frozenset({0, 2, 4}) in patterns  # Mon/Wed/Fri
    assert frozenset({1, 3}) in patterns     # Tue/Thu
    # Two full weeks of each class.
    for title, weekdays in days_by_course.items():
        assert sum(e.title == title for e in classes) == 2 * len(weekdays)


def test_one_off_events():
    one_offs = [e for e in demo_events() if not e.id.startswith("demo:class:")]
    assert 2 <= len(one_offs) <= 3
    assert any(e.start.timetz().replace(tzinfo=None) < DINNER[1]
               and e.end.timetz().replace(tzinfo=None) > DINNER[0]
               for e in one_offs), "one overlaps dinner"
