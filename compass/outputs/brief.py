"""The morning brief: the data it shows, a plain Markdown template, and saving it.

Everything is shown in local time (`BriefData.timezone`).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from ..engine.warnings import Warning
from ..models import Change, DayPlan, Task

DUE_SOON_DAYS = 14


class BriefData(BaseModel):
    date: date
    now: datetime
    timezone: str
    plan: DayPlan
    due: list[Task]           # not submitted, due before now + DUE_SOON_DAYS (overdue included)
    changes: list[Change]     # found by this run's merge, so "since the last run"
    warnings: list[Warning]
    errors: list[str]         # one line per source that failed
    titles: dict[str, str] = {}  # task ID -> title, to describe changes and unplaced tasks

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def due_soon(tasks: list[Task], now: datetime, days: int = DUE_SOON_DAYS) -> list[Task]:
    """Every task that isn't submitted and is due before `now + days`, overdue included."""
    end = now + timedelta(days=days)
    due = [t for t in tasks if not t.submitted and t.due is not None and t.due <= end]
    return sorted(due, key=lambda t: (t.due, t.id))


# --- formatting helpers -------------------------------------------------------------------

def _dur(minutes: int) -> str:
    h, m = divmod(int(minutes), 60)
    if not h:
        return f"{m} min"
    return f"{h} h" if not m else f"{h} h {m} min"


def _day(d: date) -> str:
    return f"{d:%a} {d:%b} {d.day}"


def _until(due: datetime, now: datetime) -> str:
    hours = (due - now).total_seconds() / 3600
    if hours < 0:
        return "overdue"
    if hours < 1:
        return "in under an hour"
    if hours < 48:
        return f"in {int(hours)} h"
    return f"in {int(hours // 24)} days"


def _course(task: Task) -> str:
    return f" ({task.course})" if task.course else ""


def _change_line(c: Change, data: BriefData) -> str:
    title = data.titles.get(c.entity_id, c.entity_id)

    def local(iso: str | None) -> str:
        if not iso:
            return "none"
        dt = datetime.fromisoformat(iso).astimezone(data.tz)
        return f"{_day(dt.date())} {dt:%H:%M}"

    if c.field == "due":
        return f"**{title}**: due date moved from {local(c.old)} to {local(c.new)}."
    if c.field == "status":
        if c.new == "missing":
            return f"**{title}** wasn't in the last fetch. It may have been removed or moved."
        return f"**{title}** is back after being missing."
    if c.field == "submitted":
        return (f"**{title}** is now marked submitted." if c.new == "1"
                else f"**{title}** is no longer marked submitted.")
    if c.field == "points":
        return f"**{title}**: points changed from {c.old} to {c.new}."
    if c.field == "title":
        return f"Renamed: **{c.old}** is now **{c.new}**."
    return f"**{title}**: {c.field} changed from {c.old} to {c.new}."


# --- template --------------------------------------------------------------------------------

def render_template(data: BriefData) -> str:
    tz = data.tz
    lines = [f"# Compass brief: {data.date:%A}, {data.date:%B} {data.date.day}", ""]

    for error in data.errors:
        lines.append(f"> **Source failed:** {error}. Its data is from the last good run.")
    if data.errors:
        lines.append("")

    # Today's plan
    lines += ["## Today's plan", ""]
    shown = [b for b in data.plan.blocks if b.kind != "break"]
    if shown:
        lines += ["| Time | What |", "|---|---|"]
        for b in shown:
            when = f"{b.start.astimezone(tz):%H:%M}–{b.end.astimezone(tz):%H:%M}"
            what = {"study": f"**Study:** {b.title}", "protected": f"_{b.title}_"}.get(b.kind, b.title)
            lines.append(f"| {when} | {what} |")
        lines.append("")
    study = sum(b.minutes for b in data.plan.blocks if b.kind == "study")
    if study:
        lines.append(f"Study time: {_dur(study)}, with short breaks between blocks.")
    else:
        lines.append("No study blocks today.")
    if data.plan.unplaced:
        names = ", ".join(data.titles.get(i, i) for i in data.plan.unplaced)
        lines.append(f"Didn't fit today: {names}.")
    lines.append("")

    # Due soon
    lines += [f"## Due in the next {DUE_SOON_DAYS} days", ""]
    if not data.due:
        lines += ["Nothing due.", ""]
    groups: dict[str, list[Task]] = {}
    for t in data.due:
        local_day = t.due.astimezone(tz).date()
        if t.due <= data.now:
            key = "Overdue"
        elif local_day == data.date:
            key = f"Today, {_day(local_day)}"
        elif local_day == data.date + timedelta(days=1):
            key = f"Tomorrow, {_day(local_day)}"
        else:
            key = _day(local_day)
        groups.setdefault(key, []).append(t)
    for key, tasks in groups.items():
        lines += [f"### {key}", ""]
        for t in tasks:
            due_local = t.due.astimezone(tz)
            when = (f"was due {_day(due_local.date())} {due_local:%H:%M}" if t.due <= data.now
                    else f"due {due_local:%H:%M} ({_until(t.due, data.now)})")
            work = f"~{_dur(t.remaining_minutes)} of work left" if t.remaining_minutes else "no time estimated"
            flag = " · _missing from the last fetch_" if t.missing else ""
            lines.append(f"- **{t.title}**{_course(t)} · {when} · {work}{flag}")
        lines.append("")

    # What changed
    lines += ["## What changed", ""]
    if data.changes:
        lines += [f"- {_change_line(c, data)}" for c in data.changes]
    else:
        lines.append("No changes since the last run.")
    lines.append("")

    # Warnings
    lines += ["## Warnings", ""]
    if data.warnings:
        lines += [f"- {w.message}" for w in data.warnings]
    else:
        lines.append("None.")
    lines.append("")

    return "\n".join(lines)


def save_brief(text: str, day: date, directory: Path | str = "briefs") -> Path:
    """Write `<directory>/YYYY-MM-DD.md`, replacing any brief already saved for that day."""
    path = Path(directory) / f"{day.isoformat()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
