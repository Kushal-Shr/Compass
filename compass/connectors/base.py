"""The contract every source follows. Connectors fetch only: they never touch the store."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from ..models import Event, Task


class SourceResult(BaseModel):
    source: str
    tasks: list[Task] = []
    events: list[Event] = []
    error: str = ""  # non-empty means "don't trust the lists": the result is not merged (D3)

    @property
    def ok(self) -> bool:
        return not self.error


class Source(Protocol):
    name: str

    def fetch(self, start: datetime, end: datetime) -> SourceResult: ...
