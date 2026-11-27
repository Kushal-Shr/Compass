import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from compass.models import Event, Task
from compass.store import MIGRATIONS, SCHEMA, Store

TZ = ZoneInfo("America/Chicago")
NOW = datetime(2026, 11, 30, 7, 0, tzinfo=TZ)


def make(due="2026-12-04T23:59:00-06:00", **kw):
    return Task(id="canvas:1", title="Essay", source="canvas",
                due=datetime.fromisoformat(due), points=100, est_minutes=120, **kw)


def test_first_insert_has_no_changes():
    s = Store(":memory:")
    assert s.upsert_task(make(), NOW) == []


def test_idempotent_upsert():
    s = Store(":memory:")
    s.upsert_task(make(), NOW)
    assert s.upsert_task(make(), NOW) == []
    assert len(s.get_tasks()) == 1


def test_due_date_change_detected():
    s = Store(":memory:")
    s.upsert_task(make("2026-12-04T23:59:00-06:00"), NOW)
    changes = s.upsert_task(make("2026-12-02T23:59:00-06:00"), NOW)
    assert [(c.field, c.old, c.new) for c in changes] == [
        ("due", "2026-12-05T05:59:00+00:00", "2026-12-03T05:59:00+00:00")]


def test_same_instant_in_another_offset_is_not_a_change():
    s = Store(":memory:")
    s.upsert_task(make("2026-12-04T23:59:00-06:00"), NOW)
    assert s.upsert_task(make("2026-12-05T05:59:00+00:00"), NOW) == []


def test_manual_estimate_survives_refresh():
    s = Store(":memory:")
    s.upsert_task(make(), NOW)
    s.set_estimate("canvas:1", 300, NOW)
    s.upsert_task(make(), NOW)
    assert s.get_tasks()[0].est_minutes == 300


def test_times_stored_as_utc_and_read_back_aware():
    s = Store(":memory:")
    s.upsert_task(make(), NOW)
    raw = s.db.execute("SELECT due FROM tasks").fetchone()[0]
    assert raw == "2026-12-05T05:59:00+00:00"
    due = s.get_tasks()[0].due
    assert due.tzinfo == timezone.utc
    assert due == datetime(2026, 12, 4, 23, 59, tzinfo=TZ)

    s.replace_events([Event(id="gcal:1", title="Class", start=NOW, end=NOW.replace(hour=8))])
    assert s.get_events()[0].start == NOW


def test_naive_datetime_refused():
    s = Store(":memory:")
    with pytest.raises(ValueError):
        s.upsert_task(make("2026-12-04T23:59:00"), NOW)


def test_new_database_is_fully_migrated():
    s = Store(":memory:")
    assert s.version == len(MIGRATIONS)
    assert s.get_tasks() == []


def test_old_database_gets_missing_column(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(SCHEMA)
    old.execute("INSERT INTO tasks VALUES"
                " ('canvas:9', 'Old', 'canvas', '', NULL, 0, 0, NULL, 0, 0, '')")
    old.commit()
    old.close()

    s = Store(str(path))
    assert s.version == len(MIGRATIONS)
    [task] = s.get_tasks()
    assert task.id == "canvas:9" and task.missing is False
    # Opening again doesn't re-run migrations.
    assert Store(str(path)).version == len(MIGRATIONS)


def test_event_flags_round_trip():
    s = Store(":memory:")
    e = Event(id="gcal:2", title="Trip", start=NOW, end=NOW.replace(day=2, month=12),
              all_day=True, busy=False)
    s.replace_events([e])
    assert s.get_events() == [e]
    [back] = s.get_events()
    assert back.all_day is True and back.busy is False
