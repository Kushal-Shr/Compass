import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from compass.config import Config
from compass.demo import DEMO_TODAY, demo_events, demo_tasks
from compass.engine.estimate import auto_estimates
from compass.engine.freetime import busy_blocks, day_window
from compass.engine.planner import daily_share, plan_day
from compass.models import DayPlan, Event, Task
from compass.store import Store

TZ = ZoneInfo("America/Chicago")
NOW = DEMO_TODAY
MON = NOW.date()


def make_config(**planner) -> Config:
    return Config.model_validate({
        "timezone": "America/Chicago",
        "day_window": {"start": "08:00", "end": "23:00"},
        "protected": [
            {"title": "Dinner", "start": "18:00", "end": "19:00",
             "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
            {"title": "Evening off", "start": "19:00", "end": "21:00", "days": ["fri", "sat"]},
        ],
        "planner": {"min_block_minutes": 25, "max_block_minutes": 90, "break_minutes": 10,
                    "daily_cap_minutes": 360, **planner},
        "calendars": ["primary"],
        "models": {"writer": "claude-sonnet-5-5"},
    })


CONFIG = make_config()


def at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=TZ)


def estimated_demo() -> list[Task]:
    tasks = demo_tasks()
    est = auto_estimates(tasks, overridden=())
    return [t.model_copy(update={"est_minutes": est[t.id]}) for t in tasks]


def task(id: str, due: datetime | None, est: int, points: float = 10) -> Task:
    return Task(id=id, title=id, source="demo", due=due, est_minutes=est, points=points)


def study(plan: DayPlan):
    return [b for b in plan.blocks if b.kind == "study"]


def overlaps(a, b) -> bool:
    return a.start < b.end and b.start < a.end


def check_plan(plan: DayPlan, day: date, events: list[Event], config: Config, now: datetime):
    """Every rule a plan must keep, for any input."""
    p = config.planner
    win_start, win_end = day_window(day, config)
    busy = busy_blocks(day, events, config)
    blocks = study(plan)
    breaks = [b for b in plan.blocks if b.kind == "break"]
    for b in blocks:
        assert p.min_block_minutes <= b.minutes <= p.max_block_minutes
        assert b.start.minute % 5 == 0
        assert win_start <= b.start < b.end <= win_end
        assert b.start >= now
        assert not any(overlaps(b, x) for x in busy)
    for b in blocks + breaks:
        assert not any(overlaps(b, x) for x in busy)
    placed = sorted(blocks + breaks, key=lambda b: b.start)
    for a, b in zip(placed, placed[1:]):
        assert a.end <= b.start
    assert sum(b.minutes for b in blocks) <= p.daily_cap_minutes
    assert [b.start for b in plan.blocks] == sorted(b.start for b in plan.blocks)


def test_demo_monday_plan_keeps_every_rule():
    plan = plan_day(MON, estimated_demo(), demo_events(), CONFIG, NOW)
    check_plan(plan, MON, demo_events(), CONFIG, NOW)
    assert plan.date == MON
    assert study(plan)


def test_no_study_block_overlaps_fixed_event():
    plan = plan_day(MON, estimated_demo(), demo_events(), CONFIG, NOW)
    fixed = [b for b in plan.blocks if b.kind == "fixed"]
    assert fixed
    assert not any(overlaps(s, f) for s in study(plan) for f in fixed)


def test_protected_time_never_used():
    big = [task(f"demo:{i}", at(MON, "23:59"), 600) for i in range(3)]
    plan = plan_day(MON, big, [], make_config(daily_cap_minutes=900), NOW)
    dinner = (at(MON, "18:00"), at(MON, "19:00"))
    for b in plan.blocks:
        if b.kind in ("study", "break"):
            assert not (b.start < dinner[1] and dinner[0] < b.end)
    assert any(b.kind == "protected" and b.title == "Dinner" for b in plan.blocks)


def test_blocks_stay_inside_day_window():
    big = [task("demo:1", at(MON + timedelta(days=1), "12:00"), 2000)]
    plan = plan_day(MON, big, [], make_config(daily_cap_minutes=2000), NOW)
    start, end = day_window(MON, CONFIG)
    assert all(start <= b.start and b.end <= end for b in plan.blocks)
    assert study(plan)[-1].end <= end


def test_daily_cap_respected():
    tasks = [task(f"demo:{i}", at(MON, "23:59"), 300) for i in range(4)]
    plan = plan_day(MON, tasks, [], CONFIG, NOW)
    assert sum(b.minutes for b in study(plan)) <= 360
    small_cap = plan_day(MON, tasks, [], make_config(daily_cap_minutes=100), NOW)
    assert sum(b.minutes for b in study(small_cap)) <= 100


def test_task_due_tonight_goes_first():
    tonight = task("demo:tonight", at(MON, "23:59"), 120, points=1)
    big_soon = task("demo:big", at(MON + timedelta(days=1), "09:00"), 300, points=500)
    plan = plan_day(MON, [big_soon, tonight], [], CONFIG, NOW)
    blocks = study(plan)
    tonight_blocks = [b for b in blocks if b.task_id == "demo:tonight"]
    assert sum(b.minutes for b in tonight_blocks) == 120  # all of its time
    first_other = min(b.start for b in blocks if b.task_id != "demo:tonight")
    assert all(b.start < first_other for b in tonight_blocks)


def test_demo_due_tonight_first():
    plan = plan_day(MON, estimated_demo(), demo_events(), CONFIG, NOW)
    assert study(plan)[0].task_id == "demo:101"


def test_blocks_are_25_to_90_minutes_and_split_cleanly():
    plan = plan_day(MON, [task("demo:1", at(MON, "23:59"), 100)], [], CONFIG, NOW)
    lengths = [b.minutes for b in study(plan)]
    assert sum(lengths) == 100
    assert all(25 <= m <= 90 for m in lengths)
    assert lengths == [75, 25]  # not 90 + an unusable 10


def test_break_after_each_study_block():
    plan = plan_day(MON, [task("demo:1", at(MON, "23:59"), 180)], [], CONFIG, NOW)
    blocks = [b for b in plan.blocks if b.kind in ("study", "break")]
    assert [b.kind for b in blocks] == ["study", "break", "study", "break"]
    assert blocks[1].minutes == 10


def test_short_gap_stays_empty():
    # 08:00-08:20 is free, then busy until 23:00.
    events = [Event(id="gcal:1", title="All day", start=at(MON, "08:20"), end=at(MON, "23:00"))]
    plan = plan_day(MON, [task("demo:1", at(MON, "23:59"), 60)], events, CONFIG, NOW)
    assert study(plan) == []
    assert plan.unplaced == ["demo:1"]


def test_blocks_end_by_the_due_time():
    due = at(MON, "10:00")
    plan = plan_day(MON, [task("demo:1", due, 300)], [], CONFIG, NOW)
    assert study(plan) and all(b.end <= due for b in study(plan))


def test_not_before_now_and_rounded_to_5_minutes():
    now = at(MON, "13:07")
    plan = plan_day(MON, [task("demo:1", at(MON, "23:59"), 60)], [], CONFIG, now)
    assert study(plan)[0].start == at(MON, "13:10")


def test_later_tasks_get_a_share():
    due_fri = task("demo:1", at(MON + timedelta(days=4), "23:59"), 200)
    assert daily_share(due_fri, MON, CONFIG) == 50   # 200 minutes over Mon-Thu
    undated = task("demo:2", None, 500)
    assert daily_share(undated, MON, CONFIG) == 90
    tiny = task("demo:3", at(MON + timedelta(days=9), "23:59"), 20)
    assert daily_share(tiny, MON, CONFIG) == 25      # at least one minimum block


def test_tasks_with_no_time_are_unplaced():
    tasks = [task(f"demo:{i}", at(MON, "23:59"), 90) for i in range(6)]
    plan = plan_day(MON, tasks, [], make_config(daily_cap_minutes=180), NOW)
    placed = {b.task_id for b in study(plan)}
    assert len(placed) == 2
    assert set(plan.unplaced) == {t.id for t in tasks} - placed


def test_plan_includes_busy_blocks():
    plan = plan_day(MON, estimated_demo(), demo_events(), CONFIG, NOW)
    assert {b.kind for b in plan.blocks} == {"fixed", "protected", "study", "break"}


def test_randomized_plans_never_overlap():
    rng = random.Random(7)
    for _ in range(200):
        day = MON + timedelta(days=rng.randrange(14))
        config = make_config(
            min_block_minutes=rng.choice([15, 25, 30]),
            max_block_minutes=rng.choice([45, 60, 90, 120]),
            break_minutes=rng.choice([0, 5, 10, 15]),
            daily_cap_minutes=rng.choice([60, 180, 360, 600]),
        )
        events = []
        for i in range(rng.randrange(8)):
            start = at(day, "06:00") + timedelta(minutes=rng.randrange(0, 1200, 5))
            events.append(Event(id=f"gcal:{i}", title=f"e{i}", start=start,
                                end=start + timedelta(minutes=rng.randrange(10, 300, 5))))
        tasks = []
        for i in range(rng.randrange(1, 12)):
            due = (None if rng.random() < 0.1 else
                   at(day, "00:00") + timedelta(minutes=rng.randrange(-1440, 14 * 1440, 5)))
            tasks.append(task(f"demo:{i}", due, rng.randrange(5, 900, 5),
                              points=rng.randrange(0, 200)))
        now = at(day, "00:00") + timedelta(minutes=rng.randrange(0, 1440))
        plan = plan_day(day, tasks, events, config, now)
        check_plan(plan, day, events, config, now)
        for b in study(plan):
            t = next(t for t in tasks if t.id == b.task_id)
            if t.due and t.due > now:
                assert b.end <= t.due


def test_save_then_get_plan_round_trips():
    store = Store(":memory:")
    plan = plan_day(MON, estimated_demo(), demo_events(), CONFIG, NOW)
    assert plan.unplaced  # the demo day overflows the cap, so unplaced is exercised too
    store.save_plan(plan)
    assert store.get_plan(MON) == plan
    assert store.get_plan(MON + timedelta(days=1)) is None


def test_save_plan_replaces_that_date_only():
    store = Store(":memory:")
    tue = MON + timedelta(days=1)
    mon_plan = plan_day(MON, estimated_demo(), demo_events(), CONFIG, NOW)
    tue_plan = plan_day(tue, estimated_demo(), demo_events(), CONFIG, at(tue, "07:00"))
    store.save_plan(mon_plan)
    store.save_plan(tue_plan)
    smaller = DayPlan(date=MON, blocks=mon_plan.blocks[:2], unplaced=[])
    store.save_plan(smaller)
    assert store.get_plan(MON) == smaller
    assert store.get_plan(tue) == tue_plan
