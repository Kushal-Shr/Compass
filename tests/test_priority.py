from datetime import timedelta

from compass.demo import DEMO_TODAY, demo_tasks
from compass.engine.estimate import auto_estimates
from compass.engine.priority import URGENCY_WEIGHT, rank, score
from compass.models import Task

NOW = DEMO_TODAY


def task(id="demo:1", hours=48.0, points=10.0, est=60, **kw) -> Task:
    due = None if hours is None else NOW + timedelta(hours=hours)
    return Task(id=id, title="Task", source="demo", due=due, points=points, est_minutes=est, **kw)


def estimated_demo() -> list[Task]:
    tasks = demo_tasks()
    est = auto_estimates(tasks, overridden=())
    return [t.model_copy(update={"est_minutes": est[t.id]}) for t in tasks]


def ids(tasks: list[Task]) -> list[str]:
    return [t.id for t in tasks]


def test_due_tonight_above_next_week():
    tonight = task("demo:tonight", hours=16, points=5)
    next_week = task("demo:week", hours=7 * 24, points=200, est=300)
    assert ids(rank([next_week, tonight], NOW)) == ["demo:tonight", "demo:week"]


def test_overdue_unsubmitted_ranks_first():
    overdue = task("demo:late", hours=-20, points=1, est=15)
    soon = task("demo:soon", hours=2, points=500, est=600)
    assert ids(rank([soon, overdue], NOW))[0] == "demo:late"


def test_submitted_missing_and_finished_dropped():
    tasks = [
        task("demo:open"),
        task("demo:submitted", submitted=True),
        task("demo:missing", missing=True),
        task("demo:done", est=60, done_minutes=60),
        task("demo:unestimated", est=0),
    ]
    assert ids(rank(tasks, NOW)) == ["demo:open"]


def test_more_points_wins_on_equal_due():
    small = task("demo:a", points=10)
    big = task("demo:b", points=50)
    assert ids(rank([small, big], NOW)) == ["demo:b", "demo:a"]


def test_more_work_for_less_time_ranks_higher():
    light = task("demo:a", hours=30, est=30)
    heavy = task("demo:b", hours=30, est=600)
    assert ids(rank([light, heavy], NOW)) == ["demo:b", "demo:a"]


def test_due_within_a_day_beats_plain_later_work():
    assert score(task(hours=23.9, points=0, est=5), NOW) > URGENCY_WEIGHT / 2
    assert score(task(hours=72, points=100, est=60), NOW) < URGENCY_WEIGHT / 2


def test_undated_ranks_after_dated():
    undated = task("demo:a", hours=None, points=500)
    later = task("demo:z", hours=13 * 24, points=1)
    assert ids(rank([undated, later], NOW)) == ["demo:z", "demo:a"]


def test_ties_break_by_due_then_id():
    # Same due date and same score, so the ID decides.
    a, b = task("demo:b"), task("demo:a")
    assert ids(rank([a, b], NOW)) == ["demo:a", "demo:b"]


def test_demo_rank_is_stable():
    tasks = estimated_demo()
    first = ids(rank(tasks, NOW))
    assert first == ids(rank(list(reversed(tasks)), NOW)) == ids(rank(estimated_demo(), NOW))
    assert first[0] == "demo:102"        # overdue discussion post
    assert first[1] == "demo:101"        # due tonight
    assert "demo:103" not in first       # submitted
    assert len(first) == len(tasks) - 1
