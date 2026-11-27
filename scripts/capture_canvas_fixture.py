"""Capture real Canvas responses once, scrubbed, as a test fixture.

Run from the repo root:  .venv/bin/python scripts/capture_canvas_fixture.py

It fetches the same pages the connector reads, keeps only the fields the connector uses, and
replaces every name, ID, code and URL with a fake one. Due dates, points and submission states
are kept, since the tests need them. Before saving it checks that every string in the output
is a fake pattern, a Canvas vocabulary value or a timestamp, checks for your Canvas host or an
email address, and refuses to save if one is found. It prints counts only.

Output: tests/fixtures/canvas/captured.json. Read it before committing it.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from compass.config import load_config, load_env
from compass.connectors.canvas import PER_PAGE, CanvasError, CanvasSource

OUT = Path("tests/fixtures/canvas/captured.json")
FAKE_HOST = "https://canvas.example.edu"
SUBMISSION_FIELDS = ("workflow_state", "submitted_at", "excused", "missing", "late")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
ISO_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
# Canvas's fixed vocabularies. Anything else is replaced with "other", so these fields can't carry
# free text, and they're left out of the leak check (an assignment called "Quiz" would otherwise
# match "online_quiz").
WORKFLOW_STATES = {"submitted", "unsubmitted", "graded", "pending_review"}
SUBMISSION_TYPES = {"discussion_topic", "online_quiz", "on_paper", "none", "external_tool",
                    "online_text_entry", "online_url", "online_upload", "media_recording",
                    "student_annotation", "not_graded", "wiki_page"}


def _enum(value, allowed: set[str]):
    return value if value is None or value in allowed else "other"


def _time(value):
    return value if value is None or (isinstance(value, str) and ISO_TIME.match(value)) else None


# Every string the script writes must be a fixed vocabulary value, a timestamp, or one of these
# fake patterns. Real text can't pass by coincidence, unlike a substring search for real names.
FAKE_PATTERNS = {
    "name": re.compile(r"^(Course|Assignment) \d+$"),
    "course_code": re.compile(r"^FAKE \d+$"),
    "html_url": re.compile(r"^https://canvas\.example\.edu/courses/\d+/assignments/\d+$"),
}


def _bad_strings(value, key: str = "") -> list[str]:
    """Field names of strings that aren't fake, vocabulary or timestamp values."""
    if isinstance(value, dict):
        return [bad for k, v in value.items() for bad in _bad_strings(v, k)]
    if isinstance(value, list):
        return [bad for v in value for bad in _bad_strings(v, key)]
    if not isinstance(value, str):
        return []
    ok = (
        (key in FAKE_PATTERNS and FAKE_PATTERNS[key].match(value))
        or (key in ("due_at", "submitted_at") and ISO_TIME.match(value))
        or (key == "workflow_state" and value in WORKFLOW_STATES | {"other"})
        or (key == "submission_types" and value in SUBMISSION_TYPES | {"other"})
    )
    return [] if ok else [key or "?"]


def main() -> int:
    config, secrets = load_config(), load_env()
    if not secrets.canvas_base_url or not secrets.canvas_token:
        print("Set CANVAS_BASE_URL and CANVAS_TOKEN in .env first.", file=sys.stderr)
        return 1
    source = CanvasSource(secrets.canvas_base_url, secrets.canvas_token.get_secret_value(),
                          config.tz)
    host = secrets.canvas_base_url.split("//", 1)[-1].strip("/").lower()

    try:
        course_pages = list(source.iter_pages(
            "/api/v1/courses", {"enrollment_state": "active", "per_page": PER_PAGE}))
        fixture: dict = {"courses": [], "assignments": {}}
        course_ids: dict[int, int] = {}
        assignment_ids: dict[int, int] = {}

        for page in course_pages:
            fake_page = []
            for c in page:
                if "id" not in c:
                    continue
                n = course_ids.setdefault(c["id"], 1001 + len(course_ids))
                fake = {"id": n, "name": f"Course {n}", "course_code": f"FAKE {n}"}
                if c.get("access_restricted_by_date"):
                    fake["access_restricted_by_date"] = True
                fake_page.append(fake)
            fixture["courses"].append(fake_page)

        for page in course_pages:
            for c in page:
                if "id" not in c or c.get("access_restricted_by_date"):
                    continue
                n = course_ids[c["id"]]
                pages = []
                try:
                    for apage in source.iter_pages(
                            f"/api/v1/courses/{c['id']}/assignments",
                            {"include[]": "submission", "per_page": PER_PAGE}):
                        fake_apage = []
                        for a in apage:
                            m = assignment_ids.setdefault(a["id"], 5001 + len(assignment_ids))
                            sub = a.get("submission") or {}
                            fake_apage.append({
                                "id": m,
                                "name": f"Assignment {m}",
                                "due_at": _time(a.get("due_at")),
                                "points_possible": (a.get("points_possible")
                                                    if isinstance(a.get("points_possible"),
                                                                  (int, float)) else None),
                                "submission_types": [_enum(t, SUBMISSION_TYPES)
                                                     for t in a.get("submission_types") or []],
                                "html_url": f"{FAKE_HOST}/courses/{n}/assignments/{m}",
                                "submission": {
                                    "workflow_state": _enum(sub.get("workflow_state"),
                                                            WORKFLOW_STATES),
                                    "submitted_at": _time(sub.get("submitted_at")),
                                    **{k: bool(sub.get(k)) for k in ("excused", "missing", "late")},
                                },
                            })
                        pages.append(fake_apage)
                except CanvasError:
                    pages = []  # no access to this course's assignments
                fixture["assignments"][str(n)] = pages
    except CanvasError as exc:
        print(f"Canvas capture failed: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(fixture, indent=2, sort_keys=True)
    problems = sorted(set(_bad_strings(json.loads(text))))  # check exactly what gets written
    problems = [f"an unexpected value in '{k}'" for k in problems]
    if host and host in text.lower():
        problems.append("your Canvas host")
    if EMAIL.search(text):
        problems.append("an email address")
    if problems:
        # Says what kind of string matched, never the string itself.
        print(f"Refusing to save: found {', '.join(problems)}. Nothing was written.",
              file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text + "\n", encoding="utf-8")
    n_assignments = sum(len(p) for pages in fixture["assignments"].values() for p in pages)
    print(f"Saved {OUT}: {len(course_ids)} courses, {n_assignments} assignments, "
          f"{sum(len(p) for p in fixture['courses'])} course rows in "
          f"{len(fixture['courses'])} page(s). Read it before committing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
