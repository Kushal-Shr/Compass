from __future__ import annotations

import sqlite3
from datetime import datetime

from .models import Change, Event, Task

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

# Task fields compared for change detection.
TRACKED = ("title", "due", "points", "submitted")


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


class Store:
    def __init__(self, path: str = "compass.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def upsert_task(self, t: Task, now: datetime | None = None) -> list[Change]:
        """Insert or update a task; return the tracked-field changes."""
        now = now or datetime.now()
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (t.id,)).fetchone()
        new = {"title": t.title, "due": _iso(t.due), "points": t.points,
               "submitted": int(t.submitted)}
        changes: list[Change] = []
        if row is None:
            self.db.execute(
                "INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (t.id, t.title, t.source, t.course, _iso(t.due), t.points,
                 t.est_minutes, None, t.done_minutes, int(t.submitted), t.url))
        else:
            for f in TRACKED:
                if row[f] != new[f]:
                    changes.append(Change(entity_id=t.id, field=f, old=_s(row[f]),
                                          new=_s(new[f]), detected_at=now))
            # Keep manual override and logged progress; refresh source fields.
            self.db.execute(
                "UPDATE tasks SET title=?, course=?, due=?, points=?, submitted=?, url=? WHERE id=?",
                (t.title, t.course, _iso(t.due), t.points, int(t.submitted), t.url, t.id))
        for c in changes:
            self.db.execute("INSERT INTO changes VALUES (?,?,?,?,?)",
                            (c.entity_id, c.field, c.old, c.new, _iso(c.detected_at)))
        self.db.commit()
        return changes

    def set_estimate(self, task_id: str, minutes: int) -> None:
        self.db.execute("UPDATE tasks SET est_override=? WHERE id=?", (minutes, task_id))
        self.db.commit()

    def get_tasks(self) -> list[Task]:
        out = []
        for r in self.db.execute("SELECT * FROM tasks"):
            est = r["est_override"] if r["est_override"] is not None else r["est_minutes"]
            out.append(Task(
                id=r["id"], title=r["title"], source=r["source"], course=r["course"],
                due=datetime.fromisoformat(r["due"]) if r["due"] else None,
                points=r["points"], est_minutes=est, done_minutes=r["done_minutes"],
                submitted=bool(r["submitted"]), url=r["url"]))
        return out

    def replace_events(self, events: list[Event]) -> None:
        """Calendar is a snapshot: replace all fetched events each run."""
        self.db.execute("DELETE FROM events")
        self.db.executemany(
            "INSERT INTO events VALUES (?,?,?,?,?,?)",
            [(e.id, e.title, _iso(e.start), _iso(e.end), e.kind,
              int(e.created_by_agent)) for e in events])
        self.db.commit()

    def get_events(self) -> list[Event]:
        return [Event(id=r["id"], title=r["title"],
                      start=datetime.fromisoformat(r["start"]),
                      end=datetime.fromisoformat(r["end"]), kind=r["kind"],
                      created_by_agent=bool(r["created_by_agent"]))
                for r in self.db.execute("SELECT * FROM events")]

    def log_run(self, workflow: str, started: datetime, status: str,
                errors: str = "") -> None:
        self.db.execute("INSERT INTO runs VALUES (?,?,?,?,?)",
                        (workflow, _iso(started), _iso(datetime.now()), status, errors))
        self.db.commit()


def _s(v):
    return None if v is None else str(v)
