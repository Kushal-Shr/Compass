from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Task(BaseModel):
    id: str  # source-prefixed, e.g. "canvas:12345"
    title: str
    source: str
    course: str = ""
    due: datetime | None = None
    points: float = 0
    est_minutes: int = 0
    done_minutes: int = 0
    submitted: bool = False
    url: str = ""
    missing: bool = False  # was stored but not in the last fetch (set by the store, not sources)

    @property
    def remaining_minutes(self) -> int:
        return max(self.est_minutes - self.done_minutes, 0)


class Event(BaseModel):
    id: str
    title: str
    start: datetime
    end: datetime
    kind: Literal["fixed", "protected"] = "fixed"
    created_by_agent: bool = False


BlockKind = Literal["fixed", "protected", "study", "break"]


class Block(BaseModel):
    start: datetime
    end: datetime
    kind: BlockKind
    title: str = ""
    task_id: str | None = None

    @property
    def minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


class DayPlan(BaseModel):
    date: date
    blocks: list[Block]
    unplaced: list[str] = []  # task ids that did not fit


class Change(BaseModel):
    entity_id: str
    field: str
    old: str | None
    new: str | None
    detected_at: datetime
