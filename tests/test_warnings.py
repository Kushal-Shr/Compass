import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from compass.config import Config
from compass.demo import DEMO_TODAY, demo_events, demo_tasks
from compass.engine.estimate import auto_estimates
from compass.engine.warnings import check
from compass.models import Event, Task

TZ = ZoneInfo("America/Chicago")
NOW = DEMO_TODAY  # Mon 2026-11-30 07:00
MON = NOW.date()

CONFIG = Config.model_validate({
    "timezone": "America/Chicago",
    "day_window": {"start": "08:00", "end": "23:00"},
    "protected": [{"title": "Dinner", "start": "18:00", "end": "19:00",
                   "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}],
    "planner": {"min_block_minutes": 25, "max_block_minutes": 90, "break_minutes": 10,
                "daily_cap_minutes": 360},
    "calendars": ["primary"],
    "models": {"writer": "claude-sonnet-5-5"},
})


def at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=TZ)


def task(id: str, due: datetime | None, est: int, **kw) -> Task:
    return Task(id=id, title=f"Task {id}", source="demo", course="CS 201", due=due,
                est_minutes=est, **kw)


def busy_except(day: date, free_from: str, free_to: str, id="gcal:x") -> list[Event]:
    """Events that leave only free_from-free_to open inside the 08:00-23:00 window."""
    return [Event(id=f"{id}a", title="Busy", start=at(day, "08:00"), end=at(day, free_from)),
            Event(id=f"{id}b", title="Busy", start=at(day, free_to), end=at(day, "23:00"))]


def kinds(warnings) -> list[str]:
    return [w.kind for w in warnings]


def test_ten_hour_task_due_tomorrow_with_three_free_hours_cannot_finish():
    tue = MON + timedelta(days=1)
    events = busy_except(MON, "13:00", "16:00") + busy_except(tue, "08:00", "08:00", id="gcal:y")
    big = task("demo:1", at(tue, "09:00"), 600)
    warnings = check([big], events, CONFIG, NOW)
    [cf] = [w for w in warnings if w.kind == "cannot_finish"]
    assert cf.task_id == "demo:1" and cf.date == tue
    assert "10 h" in cf.message and "3 h" in cf.message


def test_three_big_tasks_due_same_day_overloaded():
    wed = MON + timedelta(days=2)
    tasks = [task(f"demo:{i}", at(wed, "23:59"), 300) for i in range(3)]
    # 900 minutes paced over Mon-Tue is 450 a day, over the 360 daily cap.
    warnings = check(tasks, [], CONFIG, NOW)
    over = [w for w in warnings if w.kind == "overloaded_day"]
    assert len(over) == 1
    assert over[0].date == MON
    assert over[0].task_id is None
    assert "cannot_finish" not in kinds(warnings)  # each one alone fits


def test_slack_earlier_absorbs_a_busy_day():
    # Tuesday is fully booked, but a task due Wed paced over Mon-Tue fits in Monday's free time.
    tue = MON + timedelta(days=1)
    events = busy_except(tue, "08:00", "08:00")
    tasks = [task("demo:1", at(MON + timedelta(days=2), "23:59"), 300)]
    assert check(tasks, events, CONFIG, NOW) == []


def test_demo_overdue_task():
    tasks = demo_tasks()
    est = auto_estimates(tasks, ())
    tasks = [t.model_copy(update={"est_minutes": est[t.id]}) for t in tasks]
    warnings = check(tasks, demo_events(), CONFIG, NOW)
    overdue = [w for w in warnings if w.kind == "overdue"]
    assert [w.task_id for w in overdue] == ["demo:102"]
    assert "isn't submitted" in overdue[0].message
    assert "Sun Nov 29 23:59" in overdue[0].message  # local time, not UTC
    assert "demo:103" not in {w.task_id for w in warnings}  # submitted


def test_light_week_gives_no_warnings():
    tasks = [task("demo:1", at(MON + timedelta(days=2), "23:59"), 60),
             task("demo:2", at(MON + timedelta(days=5), "12:00"), 120),
             task("demo:3", None, 90),
             task("demo:4", at(MON - timedelta(days=1), "23:59"), 60, submitted=True)]
    assert check(tasks, demo_events(), CONFIG, NOW) == []


def test_missing_task_warned_not_overdue():
    gone = task("demo:1", at(MON - timedelta(days=1), "12:00"), 60, missing=True)
    warnings = check([gone], [], CONFIG, NOW)
    assert kinds(warnings) == ["missing"]
    assert "wasn't in the last demo fetch" in warnings[0].message


def test_overdue_task_with_no_time_left_still_warned():
    done_not_sent = task("demo:1", at(MON - timedelta(days=2), "23:59"), 60, done_minutes=60)
    assert kinds(check([done_not_sent], [], CONFIG, NOW)) == ["overdue"]


def test_task_beyond_horizon_skipped_for_cannot_finish():
    far = task("demo:1", at(MON + timedelta(days=20), "23:59"), 10_000)
    warnings = check([far], [], CONFIG, NOW, days=14)
    assert "cannot_finish" not in kinds(warnings)


def test_due_time_limits_free_time_on_due_day():
    # Due Mon 10:00: only 08:00-10:00 is usable, so 3 hours can't fit.
    t = task("demo:1", at(MON, "10:00"), 180)
    assert "cannot_finish" in kinds(check([t], [], CONFIG, NOW))
    t_ok = task("demo:2", at(MON, "10:00"), 90)
    assert "cannot_finish" not in kinds(check([t_ok], [], CONFIG, NOW))


def test_sorted_by_date_then_kind():
    wed = MON + timedelta(days=2)
    tasks = [task("demo:a", at(MON - timedelta(days=1), "23:59"), 30),       # overdue Sun
             task("demo:b", at(MON, "09:00"), 600),                          # cannot_finish Mon
             task("demo:c", at(MON - timedelta(days=1), "09:00"), 30, missing=True),  # missing Sun
             *[task(f"demo:w{i}", at(wed, "23:59"), 300) for i in range(3)]]
    warnings = check(tasks, [], CONFIG, NOW)
    assert [(w.date, w.kind) for w in warnings] == sorted(
        [(w.date, w.kind) for w in warnings],
        key=lambda x: (x[0], ["overdue", "missing", "cannot_finish", "overloaded_day"].index(x[1])))
    assert kinds(warnings)[:2] == ["overdue", "missing"]


def test_messages_are_plain_sentences():
    wed = MON + timedelta(days=2)
    tasks = [task("demo:1", at(MON - timedelta(days=1), "23:59"), 30),
             *[task(f"demo:w{i}", at(wed, "23:59"), 300) for i in range(3)]]
    for w in check(tasks, [], CONFIG, NOW):
        assert w.message.endswith(".")
        assert not re.search(r"\d{4}-\d{2}-\d{2}|\+00:00", w.message)  # no ISO stamps
