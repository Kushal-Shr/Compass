from datetime import datetime, timedelta

from compass.config import Config
from compass.connectors.base import SourceResult
from compass.connectors.demo import DemoSource
from compass.demo import DEMO_TODAY, demo_events, demo_tasks
from compass.models import Event, Task
from compass.orchestrator import fetch_all, morning, refresh
from compass.store import Store
from compass.cli import main

NOW = DEMO_TODAY
CONFIG = Config.model_validate({
    "timezone": "America/Chicago",
    "day_window": {"start": "08:00", "end": "23:00"},
    "protected": [{"title": "Dinner", "start": "18:00", "end": "19:00",
                   "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]}],
    "planner": {"min_block_minutes": 25, "max_block_minutes": 90, "break_minutes": 10,
                "daily_cap_minutes": 360},
    "calendars": ["primary"],
    "models": {"writer": "claude-sonnet-5-5"},
})


class Exploding:
    name = "canvas"

    def fetch(self, start: datetime, end: datetime) -> SourceResult:
        raise ConnectionError("Canvas is down")


class Erroring:
    """Returns an error result, as a connector that catches its own failure would."""

    def __init__(self, name: str = "demo"):
        self.name = name

    def fetch(self, start: datetime, end: datetime) -> SourceResult:
        return SourceResult(source=self.name, error="HTTP 503")


class Fixed:
    def __init__(self, name: str, tasks: list[Task] = (), events: list[Event] = ()):
        self.name, self.tasks, self.events = name, list(tasks), list(events)

    def fetch(self, start, end) -> SourceResult:
        return SourceResult(source=self.name, tasks=self.tasks, events=self.events)


def runs(store: Store) -> list[tuple]:
    return [tuple(r) for r in store.db.execute("SELECT workflow, status, errors FROM runs")]


def test_morning_logs_one_run_and_writes_brief(tmp_path):
    store = Store(":memory:")
    path = morning([DemoSource()], store, CONFIG, NOW, brief_dir=tmp_path)
    assert path == tmp_path / "2026-11-30.md"
    assert "## Today's plan" in path.read_text()
    assert runs(store) == [("morning", "ok", "")]
    assert store.get_plan(NOW.date()) is not None


def test_raising_source_still_produces_brief_with_error_line(tmp_path):
    store = Store(":memory:")
    path = morning([DemoSource(), Exploding()], store, CONFIG, NOW, brief_dir=tmp_path)
    text = path.read_text()
    assert "**Source failed:** canvas (ConnectionError: Canvas is down)" in text
    assert "Problem Set 7" in text  # the demo source still made it in
    assert runs(store) == [("morning", "partial", "canvas (ConnectionError: Canvas is down)")]


def test_failed_source_is_never_merged():
    store = Store(":memory:")
    refresh([DemoSource()], store, CONFIG, NOW)
    # The next run the demo source fails: nothing is marked missing and its events stay.
    r = refresh([Erroring()], store, CONFIG, NOW + timedelta(hours=1))
    assert r.changes == []
    assert not any(t.missing for t in store.get_tasks())
    assert len(store.get_events()) == len(demo_events())
    assert r.errors == ["demo (HTTP 503)"]


def test_one_sources_events_dont_wipe_anothers():
    store = Store(":memory:")
    gcal = Event(id="gcal:1", title="Dentist", start=NOW + timedelta(hours=5),
                 end=NOW + timedelta(hours=6))
    refresh([DemoSource(), Fixed("gcal", events=[gcal])], store, CONFIG, NOW)
    refresh([DemoSource(), Erroring("gcal")], store, CONFIG, NOW)
    assert "gcal:1" in {e.id for e in store.get_events()}
    refresh([Fixed("gcal", events=[])], store, CONFIG, NOW)
    ids = {e.id for e in store.get_events()}
    assert "gcal:1" not in ids and len(ids) == len(demo_events())


def test_fetch_all_keeps_order_and_catches():
    results = fetch_all([DemoSource(), Exploding()], NOW, NOW + timedelta(days=14))
    assert [r.source for r in results] == ["demo", "canvas"]
    assert results[0].ok and len(results[0].tasks) == len(demo_tasks())
    assert not results[1].ok


def test_changes_reach_the_brief(tmp_path):
    store = Store(":memory:")
    morning([DemoSource()], store, CONFIG, NOW, brief_dir=tmp_path)
    moved = [t.model_copy(update={"due": t.due + timedelta(days=2)}) if t.id == "demo:109" else t
             for t in demo_tasks()]
    path = morning([Fixed("demo", tasks=moved, events=demo_events())], store, CONFIG,
                   NOW + timedelta(hours=1), brief_dir=tmp_path)
    assert "**Problem Set 8**: due date moved from Mon Dec 7 23:59 to Wed Dec 9 23:59." in path.read_text()
    assert len(runs(store)) == 2


def test_cli_demo_commands(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.yaml").write_text(
        'timezone: America/Chicago\n'
        'day_window: {start: "08:00", end: "23:00"}\n'
        'protected: []\n'
        'planner: {min_block_minutes: 25, max_block_minutes: 90, break_minutes: 10,'
        ' daily_cap_minutes: 360}\n'
        'calendars: [primary]\n'
        'models: {writer: claude-sonnet-5-5}\n')
    assert main(["brief", "--demo"]) == 0
    assert (tmp_path / "briefs" / "demo" / "2026-11-30.md").exists()
    assert "# Compass brief" in capsys.readouterr().out
    assert main(["plan", "--demo"]) == 0
    assert "Problem Set 7" in capsys.readouterr().out
    assert main(["tasks", "--demo"]) == 0
    assert "demo:110" in capsys.readouterr().out
    assert main(["estimate", "demo:110", "90", "--demo"]) == 0
    assert main(["estimate", "demo:nope", "90", "--demo"]) == 1
    capsys.readouterr()
    assert main(["brief"]) == 1
    assert "Not connected yet" in capsys.readouterr().err
