"""Canvas connector against saved fixtures and a fake HTTP layer. No network."""

import json
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

import pytest
import requests

from compass.connectors.canvas import TOKEN_HELP, CanvasError, CanvasSource

FIXTURES = Path(__file__).parent / "fixtures" / "canvas"
TZ = ZoneInfo("America/Chicago")
HOST = "https://canvas.example.edu"
START = datetime(2026, 11, 23, tzinfo=TZ)
END = datetime(2026, 12, 14, tzinfo=TZ)
TOKEN = "fakefakefakefake"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


class FakeResponse:
    def __init__(self, status: int, body=None, next_url: str | None = None):
        self.status_code = status
        self._body = body
        self.links = {"next": {"url": next_url}} if next_url else {}

    def json(self):
        return self._body


class FakeCanvas:
    """Serves a fixture (`courses` and per-course `assignments` as lists of pages)."""

    def __init__(self, fixture: dict, host: str = HOST, overrides: dict | None = None):
        self.fixture, self.host = fixture, host
        self.overrides = overrides or {}   # path -> list of FakeResponse to return in turn
        self.calls: list[tuple[str, dict, dict]] = []

    def get(self, url, params=None, headers=None, timeout=None):
        assert timeout is not None, "every request needs a timeout"
        self.calls.append((url, params or {}, headers or {}))
        parts = urlsplit(url)
        path = parts.path
        if path in self.overrides and self.overrides[path]:
            return self.overrides[path].pop(0)
        page = int(parse_qs(parts.query).get("page", ["1"])[0])
        if path == "/api/v1/courses":
            pages = self.fixture["courses"]
        else:
            course_id = path.split("/")[4]
            pages = self.fixture["assignments"].get(course_id, [])
            if isinstance(pages, int):
                return FakeResponse(pages)
        body = pages[page - 1] if pages else []
        next_url = f"{self.host}{path}?page={page + 1}&per_page=100" if page < len(pages) else None
        return FakeResponse(200, body, next_url)


def source(fake, **kw) -> CanvasSource:
    return CanvasSource(HOST, TOKEN, TZ, session=fake, sleep=lambda s: None, **kw)


def fetch(fixture: dict, start=START, end=END):
    fake = FakeCanvas(fixture)
    src = source(fake)
    return src.fetch(start, end), src.last_stats, fake


def by_id(result):
    return {t.id: t for t in result.tasks}


def test_pagination_follows_all_pages():
    result, stats, fake = fetch(load("synthetic.json"))
    pages = [urlsplit(url).path + "?" + urlsplit(url).query for url, _, _ in fake.calls]
    assert "/api/v1/courses?page=2&per_page=100" in pages
    assert "/api/v1/courses/1001/assignments?page=2&per_page=100" in pages
    # Course 1004 is on the second course page; its 403 is skipped, not fatal.
    assert stats.courses == 2 and stats.courses_skipped == 2
    assert "canvas:5004" in by_id(result)  # from the second assignments page


def test_first_request_params_and_auth():
    _, _, fake = fetch(load("synthetic.json"))
    url, params, headers = fake.calls[0]
    assert url == f"{HOST}/api/v1/courses" and params["enrollment_state"] == "active"
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assignment_calls = [c for c in fake.calls if c[0].endswith("/assignments")]
    assert all(p["include[]"] == "submission" for _, p, _ in assignment_calls)
    assert all(TOKEN not in url for url, _, _ in fake.calls)  # never in the URL


def test_submitted_assignments_marked_submitted():
    tasks = by_id(fetch(load("synthetic.json"))[0])
    assert tasks["canvas:5002"].submitted is True    # workflow_state submitted
    assert tasks["canvas:5004"].submitted is True    # graded
    assert tasks["canvas:5006"].submitted is True    # excused
    assert tasks["canvas:5001"].submitted is False
    assert tasks["canvas:5008"].submitted is False   # no submission object


def test_due_dates_converted_to_chicago():
    tasks = by_id(fetch(load("synthetic.json"))[0])
    due = tasks["canvas:5001"].due
    assert due.tzinfo == TZ
    assert (due.date().isoformat(), f"{due:%H:%M}", due.utcoffset()) == (
        "2026-11-30", "23:59", timedelta(hours=-6))
    # After the March 2027 DST change the offset is -05:00.
    spring = by_id(fetch(load("synthetic.json"), START, datetime(2027, 4, 1, tzinfo=TZ))[0])
    quiz = spring["canvas:5007"].due
    assert (f"{quiz:%m-%d %H:%M}", quiz.utcoffset()) == ("03-19 23:59", timedelta(hours=-5))


def test_mapping_and_window():
    result, stats, _ = fetch(load("synthetic.json"))
    t = by_id(result)["canvas:5001"]
    assert (t.title, t.course, t.points, t.source) == ("Problem Set 9", "FAKE 1001", 20, "canvas")
    assert t.url == f"{HOST}/courses/1001/assignments/5001"
    assert by_id(result)["canvas:5008"].points == 0   # null points
    assert "canvas:5003" not in by_id(result)         # undated: skipped, counted
    assert "canvas:5005" not in by_id(result)         # outside window
    assert "canvas:5007" not in by_id(result)
    assert stats.model_dump() == {"courses": 2, "courses_skipped": 2, "assignments": 8,
                                  "in_window": 5, "submitted": 3, "undated": 1,
                                  "outside_window": 2}


def test_401_gives_clear_error():
    fake = FakeCanvas(load("synthetic.json"),
                      overrides={"/api/v1/courses": [FakeResponse(401, {"errors": []})]})
    with pytest.raises(CanvasError) as err:
        source(fake).fetch(START, END)
    assert str(err.value) == TOKEN_HELP
    assert "Canvas token is invalid or expired" in str(err.value)
    assert TOKEN not in str(err.value)


def test_one_retry_on_5xx():
    ok = FakeCanvas(load("synthetic.json"), overrides={"/api/v1/courses": [FakeResponse(503)]})
    assert source(ok).fetch(START, END).tasks  # retried and succeeded
    bad = FakeCanvas(load("synthetic.json"),
                     overrides={"/api/v1/courses": [FakeResponse(503), FakeResponse(502)]})
    with pytest.raises(CanvasError, match="HTTP 502"):
        source(bad).fetch(START, END)


def test_timeout_retried_once_then_clear_error():
    class Flaky(FakeCanvas):
        def __init__(self, failures):
            super().__init__(load("synthetic.json"))
            self.failures = failures

        def get(self, *a, **kw):
            if self.failures:
                self.failures -= 1
                raise requests.Timeout("read timed out")
            return super().get(*a, **kw)

    assert source(Flaky(1)).fetch(START, END).tasks
    with pytest.raises(CanvasError, match="didn't respond"):
        source(Flaky(2)).fetch(START, END)


def test_pagination_to_another_host_refused():
    fake = FakeCanvas(load("synthetic.json"), host="https://evil.example.com")
    with pytest.raises(CanvasError, match="another host"):
        source(fake).fetch(START, END)
    assert all(urlsplit(url).netloc == "canvas.example.edu" for url, _, _ in fake.calls)


def test_base_url_must_be_https():
    with pytest.raises(CanvasError, match="https"):
        CanvasSource("http://canvas.example.edu", TOKEN, TZ, session=FakeCanvas({}))


def test_repr_hides_token():
    assert TOKEN not in repr(source(FakeCanvas({})))


@pytest.mark.parametrize("name", sorted(p.name for p in FIXTURES.glob("*.json")))
def test_every_fixture_maps_cleanly(name):
    fixture = load(name)
    result, stats, _ = fetch(fixture, datetime(2000, 1, 1, tzinfo=TZ), datetime(2100, 1, 1, tzinfo=TZ))
    assert stats.in_window + stats.undated == stats.assignments
    for t in result.tasks:
        assert t.id.startswith("canvas:") and t.due.tzinfo == TZ
    text = json.dumps(fixture)
    assert "@" not in text  # no email addresses in any fixture
