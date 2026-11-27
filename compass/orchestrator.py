"""Workflows: run a pipeline end to end and log it to `runs`.

`now` (and, optionally, a clock for the finish time) is passed in. Only entry points read the clock.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel

from .config import Config
from .connectors.base import Source, SourceResult
from .engine.estimate import auto_estimates
from .engine.merge import merge_events, merge_tasks
from .engine.planner import plan_day
from .engine.warnings import Warning, check
from .models import Change, DayPlan, Event, Task
from .outputs.brief import BriefData, due_soon, render_template, save_brief
from .store import Store

FETCH_PAST_DAYS = 7    # fetch a week back, so recently overdue work is seen
FETCH_AHEAD_DAYS = 14
ERROR_MAX_CHARS = 200


def apply_estimates(store: Store) -> int:
    """Set the automatic estimate for every task without a manual override. Returns how many."""
    estimates = auto_estimates(store.get_tasks(), store.get_overrides())
    for task_id, minutes in estimates.items():
        store.set_auto_estimate(task_id, minutes)
    return len(estimates)


def _error_text(exc: BaseException) -> str:
    # Exception text from a connector could, in theory, carry a URL or header; keep it short.
    # Connectors are responsible for never putting secrets in their exceptions.
    return f"{type(exc).__name__}: {exc}"[:ERROR_MAX_CHARS]


def fetch_all(sources: Sequence[Source], start: datetime, end: datetime) -> list[SourceResult]:
    """Fetch every source in parallel threads. A source that raises becomes an error result."""
    def one(source: Source) -> SourceResult:
        try:
            result = source.fetch(start, end)
        except Exception as exc:  # noqa: BLE001 - one bad source must not stop the run
            return SourceResult(source=source.name, error=_error_text(exc))
        return result

    if not sources:
        return []
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        return list(pool.map(one, sources))


class Refresh(BaseModel):
    """Everything one fetch-merge-estimate-plan-warn pass produced."""
    results: list[SourceResult]
    changes: list[Change]
    tasks: list[Task]
    events: list[Event]
    plan: DayPlan
    warnings: list[Warning]

    @property
    def errors(self) -> list[str]:
        return [f"{r.source} ({r.error})" for r in self.results if not r.ok]


def refresh(sources: Sequence[Source], store: Store, config: Config, now: datetime) -> Refresh:
    """Fetch, merge (main thread), estimate, plan today and check warnings. Saves today's plan."""
    window = (now - timedelta(days=FETCH_PAST_DAYS), now + timedelta(days=FETCH_AHEAD_DAYS))
    results = fetch_all(sources, *window)

    changes: list[Change] = []
    for r in results:
        if not r.ok:
            continue  # D3: a failed source is never merged
        changes += merge_tasks(store, r.source, r.tasks, now, window)
        merge_events(store, r.events, source=r.source)

    apply_estimates(store)
    tasks, events = store.get_tasks(), store.get_events()
    today = now.astimezone(config.tz).date()
    plan = plan_day(today, tasks, events, config, now)
    store.save_plan(plan)
    warnings = check(tasks, events, config, now)
    return Refresh(results=results, changes=changes, tasks=tasks, events=events, plan=plan,
                   warnings=warnings)


def brief_data(r: Refresh, config: Config, now: datetime) -> BriefData:
    return BriefData(
        date=r.plan.date, now=now, timezone=config.timezone, plan=r.plan,
        due=due_soon(r.tasks, now), changes=r.changes, warnings=r.warnings, errors=r.errors,
        titles={t.id: t.title for t in r.tasks},
    )


def morning(sources: Sequence[Source], store: Store, config: Config, now: datetime,
            brief_dir: Path | str = "briefs",
            clock: Callable[[], datetime] | None = None) -> Path:
    """The morning run: refresh, render the brief, save it, and log one `runs` row.

    The run is `ok`, `partial` (some source failed) or `failed` (the pipeline itself raised; the
    exception is re-raised after logging). `clock` gives the finish time; without it, `now` is used.
    """
    def finish(status: str, errors: str) -> None:
        store.log_run("morning", now, clock() if clock else now, status, errors)

    try:
        r = refresh(sources, store, config, now)
        path = save_brief(render_template(brief_data(r, config, now)), r.plan.date, brief_dir)
    except Exception as exc:
        finish("failed", _error_text(exc))
        raise
    finish("partial" if r.errors else "ok", "; ".join(r.errors))
    return path
