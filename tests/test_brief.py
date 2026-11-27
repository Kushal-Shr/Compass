from datetime import timedelta

from compass.config import Config
from compass.connectors.demo import DemoSource
from compass.demo import DEMO_TODAY, demo_tasks
from compass.models import Change
from compass.orchestrator import brief_data, refresh
from compass.outputs.brief import due_soon, render_template, save_brief
from compass.store import Store

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


def demo_brief() -> str:
    r = refresh([DemoSource()], Store(":memory:"), CONFIG, NOW)
    return render_template(brief_data(r, CONFIG, NOW))


def test_template_lists_every_unsubmitted_demo_task_due_in_14_days():
    text = demo_brief()
    end = NOW + timedelta(days=14)
    expected = [t for t in demo_tasks() if not t.submitted and t.due <= end]
    assert expected
    for t in expected:
        assert f"**{t.title}**" in text, t.title
    for t in demo_tasks():
        if t.submitted:
            assert f"**{t.title}**" not in text.split("## Due in")[1]


def test_template_sections_and_local_times():
    text = demo_brief()
    for heading in ("# Compass brief: Monday, November 30", "## Today's plan",
                    "## Due in the next 14 days", "## What changed", "## Warnings"):
        assert heading in text
    assert "### Overdue" in text and "### Today, Mon Nov 30" in text
    assert "| 09:00–09:50 | CS 201 Data Structures lecture |" in text  # local, not UTC
    assert "+00:00" not in text
    assert "Source failed" not in text


def test_due_soon_includes_overdue_excludes_submitted_and_far():
    ids = [t.id for t in due_soon(demo_tasks(), NOW)]
    assert ids[0] == "demo:102"  # overdue first
    assert "demo:103" not in ids
    assert ids == sorted(ids, key=lambda i: next(t.due for t in demo_tasks() if t.id == i))


def test_changes_are_described_in_words():
    store = Store(":memory:")
    refresh([DemoSource()], store, CONFIG, NOW)
    r = refresh([DemoSource()], store, CONFIG, NOW)
    data = brief_data(r, CONFIG, NOW)
    data.changes = [
        Change(entity_id="demo:101", field="due", old="2026-12-01T05:59:00+00:00",
               new="2026-12-03T05:59:00+00:00", detected_at=NOW),
        Change(entity_id="demo:108", field="status", old="present", new="missing", detected_at=NOW),
    ]
    text = render_template(data)
    assert "**Problem Set 7**: due date moved from Mon Nov 30 23:59 to Wed Dec 2 23:59." in text
    assert "**Essay: Causes of Industrialization** wasn't in the last fetch." in text


def test_save_brief_writes_dated_file(tmp_path):
    path = save_brief("# hi\n", NOW.date(), tmp_path / "briefs")
    assert path == tmp_path / "briefs" / "2026-11-30.md"
    assert path.read_text() == "# hi\n"
    save_brief("# again\n", NOW.date(), tmp_path / "briefs")
    assert path.read_text() == "# again\n"
