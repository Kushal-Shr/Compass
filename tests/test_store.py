from datetime import datetime

from compass.models import Task
from compass.store import Store


def make(due="2026-12-04T23:59:00", **kw):
    return Task(id="canvas:1", title="Essay", source="canvas",
                due=datetime.fromisoformat(due), points=100, est_minutes=120, **kw)


def test_first_insert_has_no_changes():
    s = Store(":memory:")
    assert s.upsert_task(make()) == []


def test_idempotent_upsert():
    s = Store(":memory:")
    s.upsert_task(make())
    assert s.upsert_task(make()) == []
    assert len(s.get_tasks()) == 1


def test_due_date_change_detected():
    s = Store(":memory:")
    s.upsert_task(make("2026-12-04T23:59:00"))
    changes = s.upsert_task(make("2026-12-02T23:59:00"))
    assert [(c.field, c.old, c.new) for c in changes] == [
        ("due", "2026-12-04T23:59:00", "2026-12-02T23:59:00")]


def test_manual_estimate_survives_refresh():
    s = Store(":memory:")
    s.upsert_task(make())
    s.set_estimate("canvas:1", 300)
    s.upsert_task(make())
    assert s.get_tasks()[0].est_minutes == 300
