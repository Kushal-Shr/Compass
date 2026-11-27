"""Canvas: active courses and their assignments, as Tasks.

Each course's assignments are fetched without a `bucket` filter, and code keeps the ones due
inside the fetch window. (`bucket=upcoming` only covers about a week, too short for a 14-day plan.)
Assignments with no due date are skipped but counted.

The token goes in an Authorization header only, and only to `base_url`'s host: pagination links
to any other host are refused. Error messages never include the token.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel

from ..models import Task
from .base import SourceResult

TIMEOUT = (10, 30)  # connect, read (seconds)
PER_PAGE = 100
RETRY_DELAY_SECONDS = 2.0
SUBMITTED_STATES = {"submitted", "graded", "pending_review"}
TOKEN_HELP = ("Canvas token is invalid or expired. Make a new one in Canvas (Account > Settings > "
              "New access token) and put it in .env as CANVAS_TOKEN.")


class CanvasError(Exception):
    pass


class CanvasStats(BaseModel):
    courses: int = 0
    courses_skipped: int = 0   # no access (403/404) or date-restricted
    assignments: int = 0       # everything seen, before filtering
    in_window: int = 0         # became Tasks
    submitted: int = 0         # of those in the window
    undated: int = 0
    outside_window: int = 0


class CanvasSource:
    name = "canvas"

    def __init__(self, base_url: str, token: str, tz: ZoneInfo, session: Any = None,
                 sleep: Callable[[float], None] = time.sleep):
        parts = urlsplit(base_url.rstrip("/"))
        if parts.scheme != "https" or not parts.netloc:
            raise CanvasError("CANVAS_BASE_URL must be an https:// address, e.g. "
                              "https://your-school.instructure.com")
        self._base = f"https://{parts.netloc}"
        self._host = parts.netloc
        self._token = token
        self._tz = tz
        self._session = session or requests.Session()
        self._sleep = sleep
        self.last_stats = CanvasStats()

    def __repr__(self) -> str:
        return f"CanvasSource(host={self._host!r})"

    # --- HTTP ----------------------------------------------------------------------------

    def _get(self, url: str, params: dict | None) -> Any:
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
        for attempt in (1, 2):
            try:
                response = self._session.get(url, params=params, headers=headers, timeout=TIMEOUT)
            except (requests.Timeout, requests.ConnectionError) as exc:
                if attempt == 2:
                    raise CanvasError(f"Canvas didn't respond ({type(exc).__name__})") from None
                self._sleep(RETRY_DELAY_SECONDS)
                continue
            if response.status_code >= 500 and attempt == 1:
                self._sleep(RETRY_DELAY_SECONDS)
                continue
            return response
        return response

    def iter_pages(self, path: str, params: dict) -> Iterator[list[dict]]:
        """Yield each page's JSON list, following `Link: rel="next"` on the same host only."""
        url: str | None = f"{self._base}{path}"
        first = True
        while url:
            response = self._get(url, params if first else None)
            first = False
            status = response.status_code
            if status == 401:
                raise CanvasError(TOKEN_HELP)
            if status in (403, 404):
                raise _NoAccess(status)
            if status >= 400:
                raise CanvasError(f"Canvas returned HTTP {status} for {path}")
            yield response.json()
            url = (response.links.get("next") or {}).get("url")
            if url and urlsplit(url).netloc != self._host:
                raise CanvasError("Canvas pagination pointed at another host; stopped.")

    # --- mapping -------------------------------------------------------------------------

    def _task(self, a: dict, course: dict, start: datetime, end: datetime,
              stats: CanvasStats) -> Task | None:
        stats.assignments += 1
        if not a.get("due_at"):
            stats.undated += 1
            return None
        due = datetime.fromisoformat(a["due_at"].replace("Z", "+00:00")).astimezone(self._tz)
        if not start <= due <= end:
            stats.outside_window += 1
            return None
        sub = a.get("submission") or {}
        submitted = (sub.get("workflow_state") in SUBMITTED_STATES
                     or bool(sub.get("submitted_at")) or bool(sub.get("excused")))
        stats.in_window += 1
        stats.submitted += submitted
        return Task(
            id=f"canvas:{a['id']}", title=a.get("name") or "Untitled assignment",
            source=self.name, course=course.get("course_code") or course.get("name") or "",
            due=due, points=a.get("points_possible") or 0, submitted=submitted,
            url=a.get("html_url") or "",
        )

    def fetch(self, start: datetime, end: datetime) -> SourceResult:
        stats = CanvasStats()
        tasks: list[Task] = []
        courses = [c for page in self.iter_pages(
            "/api/v1/courses", {"enrollment_state": "active", "per_page": PER_PAGE}) for c in page]
        for course in courses:
            if "id" not in course or course.get("access_restricted_by_date"):
                stats.courses_skipped += 1
                continue
            stats.courses += 1
            try:
                for page in self.iter_pages(
                        f"/api/v1/courses/{course['id']}/assignments",
                        {"include[]": "submission", "per_page": PER_PAGE}):
                    for a in page:
                        if task := self._task(a, course, start, end, stats):
                            tasks.append(task)
            except _NoAccess:
                stats.courses -= 1
                stats.courses_skipped += 1
        self.last_stats = stats
        return SourceResult(source=self.name, tasks=tasks)


class _NoAccess(CanvasError):
    def __init__(self, status: int):
        super().__init__(f"Canvas denied access (HTTP {status})")
