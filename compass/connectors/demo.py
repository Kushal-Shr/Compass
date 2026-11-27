"""Fake source for `--demo`: returns the fixed demo data, whatever window is asked for."""

from __future__ import annotations

from datetime import datetime

from ..demo import demo_events, demo_tasks
from .base import SourceResult


class DemoSource:
    name = "demo"

    def fetch(self, start: datetime, end: datetime) -> SourceResult:
        return SourceResult(source=self.name, tasks=demo_tasks(), events=demo_events())
