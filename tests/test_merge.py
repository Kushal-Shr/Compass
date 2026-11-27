from datetime import timedelta

import pytest

from compass.demo import DEMO_TODAY, demo_events, demo_tasks
from compass.engine.merge import merge_events, merge_tasks
from compass.models import Task
from compass.store import Store

NOW = DEMO_TODAY
WINDOW = (NOW - timedelta(days=7), NOW + timedelta(days=14))
LATER = NOW + timedelta(days=1)


def _merged() -> Store:
    store = Store(":memory:")
    assert merge_tasks(store, "demo", demo_tasks(), NOW, WINDOW) == []
    return store


def _without(task_id: str) -> list[Task]:
    return [t for t in demo_tasks() if t.id != task_id]


def test_first_merge_has_no_changes():
    store = _merged()
    assert len(store.get_tasks()) == len(demo_tasks())
    assert store.get_changes() == []


def test_due_date_change():
    store = _merged()
    tasks = demo_tasks()
    tasks[0] = tasks[0].model_copy(update={"due": tasks[0].due + timedelta(days=2)})
    changes = merge_tasks(store, "demo", tasks, LATER, WINDOW)
    assert [(c.entity_id, c.field) for c in changes] == [(tasks[0].id, "due")]


def test_disappeared_task_marked_missing_once():
    store = _merged()
    changes = merge_tasks(store, "demo", _without("demo:108"), LATER, WINDOW)
    assert [(c.entity_id, c.field, c.old, c.new) for c in changes] == [
        ("demo:108", "status", "present", "missing")]
    assert merge_tasks(store, "demo", _without("demo:108"), LATER, WINDOW) == []
    assert {t.id for t in store.get_tasks() if t.missing} == {"demo:108"}
    assert len(store.get_changes()) == 1


def test_returning_task_clears_missing():
    store = _merged()
    merge_tasks(store, "demo", _without("demo:108"), LATER, WINDOW)
    changes = merge_tasks(store, "demo", demo_tasks(), LATER, WINDOW)
    assert [(c.entity_id, c.field, c.old, c.new) for c in changes] == [
        ("demo:108", "status", "missing", "present")]
    assert not any(t.missing for t in store.get_tasks())


def test_other_source_never_marked_missing():
    store = _merged()
    other = Task(id="canvas:1", title="Essay", source="canvas", due=NOW + timedelta(days=3))
    merge_tasks(store, "canvas", [other], NOW, WINDOW)
    # A demo fetch that returns nothing must not touch the canvas task.
    merge_tasks(store, "demo", [], LATER, WINDOW)
    assert next(t for t in store.get_tasks() if t.id == "canvas:1").missing is False


def test_submitted_past_due_and_outside_window_not_marked_missing():
    store = _merged()
    far = Task(id="demo:900", title="Far-off reading", source="demo",
               due=NOW + timedelta(days=30))
    undated = Task(id="demo:901", title="Undated reading", source="demo")
    merge_tasks(store, "demo", demo_tasks() + [far, undated], NOW, WINDOW)

    changes = merge_tasks(store, "demo", [], LATER, WINDOW)
    missing = {c.entity_id for c in changes}
    assert "demo:103" not in missing  # submitted
    assert "demo:102" not in missing  # past due
    assert "demo:101" not in missing  # due tonight, now past due at LATER
    assert "demo:900" not in missing  # outside the fetched window
    assert "demo:901" not in missing  # undated
    assert "demo:110" in missing      # future, in window, not submitted


def test_manual_estimate_survives_merge():
    store = _merged()
    store.set_estimate("demo:110", 600, NOW)
    merge_tasks(store, "demo", demo_tasks(), LATER, WINDOW)
    assert next(t for t in store.get_tasks() if t.id == "demo:110").est_minutes == 600


def test_wrong_source_refused():
    store = Store(":memory:")
    with pytest.raises(ValueError):
        merge_tasks(store, "canvas", demo_tasks(), NOW, WINDOW)


def test_merge_events_replaces_snapshot():
    store = Store(":memory:")
    merge_events(store, demo_events())
    merge_events(store, demo_events()[:3])
    assert [e.id for e in store.get_events()] == [e.id for e in demo_events()[:3]]
