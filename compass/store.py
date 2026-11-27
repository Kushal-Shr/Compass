from __future__ import annotations

import sqlite3
import uuid
from datetime import date, datetime, timezone

from .models import Block, Change, DayPlan, Event, Task

# Version 0. Never edit: later changes go in MIGRATIONS.
SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY, title TEXT, source TEXT, course TEXT, due TEXT,
  points REAL, est_minutes INTEGER, est_override INTEGER, done_minutes INTEGER,
  submitted INTEGER, url TEXT
);
CREATE TABLE IF NOT EXISTS events (
  id TEXT PRIMARY KEY, title TEXT, start TEXT, end TEXT, kind TEXT,
  created_by_agent INTEGER
);
CREATE TABLE IF NOT EXISTS plans (
  date TEXT, block_start TEXT, block_end TEXT, kind TEXT, task_id TEXT
);
CREATE TABLE IF NOT EXISTS changes (
  entity_id TEXT, field TEXT, old TEXT, new TEXT, detected_at TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  workflow TEXT, started TEXT, finished TEXT, status TEXT, errors TEXT
);
CREATE TABLE IF NOT EXISTS llm_calls (
  agent TEXT, model TEXT, input_tokens INTEGER, output_tokens INTEGER,
  cost REAL, cache_hit INTEGER, ts TEXT
);
"""

# Migration N (1-based) brings the database to `PRAGMA user_version` N. Append only.
MIGRATIONS = [
    "ALTER TABLE tasks ADD COLUMN missing INTEGER DEFAULT 0;",  # 1 (step 1.3)
    # 2 (step 1.4, D5): manual estimates become append-only user rows. Existing values from
    # tasks.est_override (no longer read) are copied over with an epoch timestamp, so any
    # newer override wins.
    """
    CREATE TABLE estimate_overrides (
      id TEXT PRIMARY KEY, task_id TEXT NOT NULL, minutes INTEGER NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX estimate_overrides_task ON estimate_overrides (task_id);
    INSERT INTO estimate_overrides (id, task_id, minutes, created_at)
      SELECT lower(hex(randomblob(16))), id, est_override, '1970-01-01T00:00:00+00:00'
      FROM tasks WHERE est_override IS NOT NULL;
    """,
    # 3 (step 1.6): all-day and free/busy flags on events.
    """
    ALTER TABLE events ADD COLUMN all_day INTEGER DEFAULT 0;
    ALTER TABLE events ADD COLUMN busy INTEGER DEFAULT 1;
    """,
    # 4 (step 1.7): block titles, and the tasks a plan couldn't fit, so a plan round-trips.
    """
    ALTER TABLE plans ADD COLUMN title TEXT DEFAULT '';
    CREATE TABLE plan_unplaced (date TEXT NOT NULL, position INTEGER NOT NULL, task_id TEXT NOT NULL);
    """,
]

# Task fields compared for change detection.
TRACKED = ("title", "due", "points", "submitted")


def _iso(d: datetime | None) -> str | None:
    """Datetimes are stored as UTC ISO strings (D2). Naive datetimes are a bug, so they're refused."""
    if d is None:
        return None
    if d.utcoffset() is None:
        raise ValueError(f"naive datetime given to the store: {d!r}")
    return d.astimezone(timezone.utc).isoformat()


def _dt(s: str | None) -> datetime | None:
    """Read back as an aware UTC datetime."""
    return datetime.fromisoformat(s).astimezone(timezone.utc) if s else None


class Store:
    def __init__(self, path: str = "compass.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
            self.db.executescript(f"BEGIN; {sql} PRAGMA user_version = {number}; COMMIT;")

    @property
    def version(self) -> int:
        return self.db.execute("PRAGMA user_version").fetchone()[0]

    def upsert_task(self, t: Task, now: datetime) -> list[Change]:
        """Insert or update a task; return the tracked-field changes.

        A task that was marked missing and comes back is cleared, with a `status` change.
        """
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (t.id,)).fetchone()
        new = {"title": t.title, "due": _iso(t.due), "points": t.points,
               "submitted": int(t.submitted)}
        changes: list[Change] = []
        if row is None:
            self.db.execute(
                "INSERT INTO tasks (id, title, source, course, due, points, est_minutes,"
                " est_override, done_minutes, submitted, url, missing)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,0)",
                (t.id, t.title, t.source, t.course, new["due"], t.points,
                 t.est_minutes, None, t.done_minutes, new["submitted"], t.url))
        else:
            for f in TRACKED:
                if row[f] != new[f]:
                    changes.append(Change(entity_id=t.id, field=f, old=_s(row[f]),
                                          new=_s(new[f]), detected_at=now))
            if row["missing"]:
                changes.append(Change(entity_id=t.id, field="status", old="missing",
                                      new="present", detected_at=now))
            # Keep manual override and logged progress; refresh source fields.
            self.db.execute(
                "UPDATE tasks SET title=?, course=?, due=?, points=?, submitted=?, url=?,"
                " missing=0 WHERE id=?",
                (t.title, t.course, new["due"], t.points, new["submitted"], t.url, t.id))
        self._record(changes)
        self.db.commit()
        return changes

    def mark_missing(self, task_id: str, now: datetime) -> Change | None:
        """Mark a stored task missing. Returns None if it's unknown or already missing."""
        cur = self.db.execute(
            "UPDATE tasks SET missing=1 WHERE id=? AND missing=0", (task_id,))
        if cur.rowcount == 0:
            return None
        change = Change(entity_id=task_id, field="status", old="present", new="missing",
                        detected_at=now)
        self._record([change])
        self.db.commit()
        return change

    def _record(self, changes: list[Change]) -> None:
        self.db.executemany("INSERT INTO changes VALUES (?,?,?,?,?)",
                            [(c.entity_id, c.field, c.old, c.new, _iso(c.detected_at))
                             for c in changes])

    def set_estimate(self, task_id: str, minutes: int, now: datetime) -> None:
        """Record a manual estimate (user data, D5): an append-only row, and the latest wins."""
        if minutes < 0:
            raise ValueError(f"estimate must not be negative: {minutes}")
        if self.db.execute("SELECT 1 FROM tasks WHERE id=?", (task_id,)).fetchone() is None:
            raise KeyError(f"unknown task: {task_id}")
        self.db.execute("INSERT INTO estimate_overrides VALUES (?,?,?,?)",
                        (uuid.uuid4().hex, task_id, minutes, _iso(now)))
        self.db.commit()

    def get_overrides(self) -> dict[str, int]:
        """Latest manual estimate per task. Ties on time break by id, so every copy agrees."""
        rows = self.db.execute(
            "SELECT task_id, minutes FROM estimate_overrides ORDER BY created_at, id")
        return {r["task_id"]: r["minutes"] for r in rows}

    def set_auto_estimate(self, task_id: str, minutes: int) -> None:
        """Set the automatic estimate. Manual overrides are separate and untouched."""
        self.db.execute("UPDATE tasks SET est_minutes=? WHERE id=?", (minutes, task_id))
        self.db.commit()

    def get_tasks(self, source: str | None = None) -> list[Task]:
        if source is None:
            rows = self.db.execute("SELECT * FROM tasks")
        else:
            rows = self.db.execute("SELECT * FROM tasks WHERE source=?", (source,))
        overrides = self.get_overrides()
        out = []
        for r in rows:
            est = overrides.get(r["id"], r["est_minutes"])
            out.append(Task(
                id=r["id"], title=r["title"], source=r["source"], course=r["course"],
                due=_dt(r["due"]), points=r["points"], est_minutes=est,
                done_minutes=r["done_minutes"], submitted=bool(r["submitted"]), url=r["url"],
                missing=bool(r["missing"])))
        return out

    def replace_events(self, events: list[Event], source: str | None = None) -> None:
        """Calendar is a snapshot: replace fetched events each run.

        With `source`, only that source's events (IDs starting `source:`) are replaced, so a
        failed fetch from one calendar never wipes another's events. Without it, all are.
        """
        if source is not None:
            wrong = [e.id for e in events if not e.id.startswith(f"{source}:")]
            if wrong:
                raise ValueError(f"events not from {source!r}: {wrong}")
        rows = [(e.id, e.title, _iso(e.start), _iso(e.end), e.kind, int(e.created_by_agent),
                 int(e.all_day), int(e.busy))
                for e in events]
        if source is None:
            self.db.execute("DELETE FROM events")
        else:
            prefix = f"{source}:"
            self.db.execute("DELETE FROM events WHERE substr(id, 1, ?) = ?", (len(prefix), prefix))
        self.db.executemany(
            "INSERT INTO events (id, title, start, end, kind, created_by_agent, all_day, busy)"
            " VALUES (?,?,?,?,?,?,?,?)", rows)
        self.db.commit()

    def get_events(self) -> list[Event]:
        return [Event(id=r["id"], title=r["title"], start=_dt(r["start"]), end=_dt(r["end"]),
                      kind=r["kind"], created_by_agent=bool(r["created_by_agent"]),
                      all_day=bool(r["all_day"]), busy=bool(r["busy"]))
                for r in self.db.execute("SELECT * FROM events")]

    def get_changes(self) -> list[Change]:
        return [Change(entity_id=r["entity_id"], field=r["field"], old=r["old"], new=r["new"],
                       detected_at=_dt(r["detected_at"]))
                for r in self.db.execute("SELECT * FROM changes ORDER BY rowid")]

    def save_plan(self, plan: DayPlan) -> None:
        """Replace the stored plan for `plan.date`."""
        day = plan.date.isoformat()
        with self.db:
            self.db.execute("DELETE FROM plans WHERE date=?", (day,))
            self.db.execute("DELETE FROM plan_unplaced WHERE date=?", (day,))
            self.db.executemany(
                "INSERT INTO plans (date, block_start, block_end, kind, task_id, title)"
                " VALUES (?,?,?,?,?,?)",
                [(day, _iso(b.start), _iso(b.end), b.kind, b.task_id, b.title)
                 for b in plan.blocks])
            self.db.executemany("INSERT INTO plan_unplaced VALUES (?,?,?)",
                                [(day, i, task_id) for i, task_id in enumerate(plan.unplaced)])

    def get_plan(self, day: date) -> DayPlan | None:
        key = day.isoformat()
        rows = self.db.execute(
            "SELECT * FROM plans WHERE date=? ORDER BY block_start, rowid", (key,)).fetchall()
        unplaced = [r["task_id"] for r in self.db.execute(
            "SELECT task_id FROM plan_unplaced WHERE date=? ORDER BY position", (key,))]
        if not rows and not unplaced:
            return None
        return DayPlan(date=day, unplaced=unplaced, blocks=[
            Block(start=_dt(r["block_start"]), end=_dt(r["block_end"]), kind=r["kind"],
                  title=r["title"] or "", task_id=r["task_id"])
            for r in rows])

    def log_run(self, workflow: str, started: datetime, finished: datetime, status: str,
                errors: str = "") -> None:
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?)",
                        (workflow, _iso(started), _iso(finished), status, errors))
        self.db.commit()


def _s(v):
    return None if v is None else str(v)
