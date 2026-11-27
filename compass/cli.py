"""`compass` command line. The entry point reads the clock and loads settings; nothing below does."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

from pydantic import ValidationError

from .config import Config, load_config
from .connectors.demo import DemoSource
from .demo import DEMO_TODAY
from .orchestrator import morning, refresh
from .store import Store

NOT_CONNECTED = "Not connected yet. Run with --demo."
DEMO_BRIEF_DIR = Path("briefs") / "demo"  # keeps demo briefs apart from real ones of the same date


def _demo_setup() -> tuple[Store, Config, datetime]:
    return Store(":memory:"), load_config(), DEMO_TODAY


def _cmd_brief(args: argparse.Namespace) -> int:
    if not args.demo:
        print(NOT_CONNECTED, file=sys.stderr)
        return 1
    store, config, now = _demo_setup()
    path = morning([DemoSource()], store, config, now, brief_dir=DEMO_BRIEF_DIR)
    print(path.read_text(encoding="utf-8"))
    print(f"Saved to {path}", file=sys.stderr)
    return 0


def _cmd_plan(args: argparse.Namespace) -> int:
    if not args.demo:
        print(NOT_CONNECTED, file=sys.stderr)
        return 1
    store, config, now = _demo_setup()
    plan = refresh([DemoSource()], store, config, now).plan
    tz = config.tz
    print(f"Plan for {plan.date:%A %Y-%m-%d}\n")
    print(f"{'Time':<13} {'Kind':<10} What")
    for b in plan.blocks:
        print(f"{b.start.astimezone(tz):%H:%M}–{b.end.astimezone(tz):%H:%M}   {b.kind:<10} {b.title}")
    study = sum(b.minutes for b in plan.blocks if b.kind == "study")
    print(f"\nStudy: {study} min (cap {config.planner.daily_cap_minutes})")
    if plan.unplaced:
        print(f"Didn't fit: {', '.join(plan.unplaced)}")
    return 0


def _cmd_tasks(args: argparse.Namespace) -> int:
    if not args.demo:
        print(NOT_CONNECTED, file=sys.stderr)
        return 1
    store, config, now = _demo_setup()
    tasks = refresh([DemoSource()], store, config, now).tasks
    tz = config.tz
    print(f"{'ID':<12} {'Due':<17} {'Est':>5}  {'Status':<10} Title")
    for t in sorted(tasks, key=lambda t: (t.due is None, t.due or now, t.id)):
        due = f"{t.due.astimezone(tz):%a %m-%d %H:%M}" if t.due else "-"
        status = "submitted" if t.submitted else "missing" if t.missing else ""
        print(f"{t.id:<12} {due:<17} {t.est_minutes:>4}m  {status:<10} {t.title}")
    return 0


def _cmd_estimate(args: argparse.Namespace) -> int:
    if not args.demo:
        print(NOT_CONNECTED, file=sys.stderr)
        return 1
    store, config, now = _demo_setup()
    refresh([DemoSource()], store, config, now)
    try:
        store.set_estimate(args.task_id, args.minutes, now)
    except (KeyError, ValueError) as exc:
        print(f"Error: {exc.args[0]}", file=sys.stderr)
        return 1
    print(f"Set {args.task_id} to {args.minutes} min (demo database, not saved).")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="compass", description="Personal study planner.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help: str, func) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help)
        p.add_argument("--demo", action="store_true", help="use fake data and no accounts")
        p.set_defaults(func=func)
        return p

    add("brief", "build today's plan and write the morning brief", _cmd_brief)
    add("plan", "print today's plan as a table", _cmd_plan)
    add("tasks", "list tasks with IDs, due dates and estimates", _cmd_tasks)
    est = add("estimate", "set your own estimate for a task", _cmd_estimate)
    est.add_argument("task_id")
    est.add_argument("minutes", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as exc:
        if Path(exc.filename or "").name != "config.yaml":
            raise
        print("config.yaml not found. Run compass from the Compass folder.", file=sys.stderr)
        return 1
    except ValidationError as exc:
        print(f"config.yaml is invalid:\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
