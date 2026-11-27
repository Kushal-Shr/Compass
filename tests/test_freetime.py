import random
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from compass.config import Config
from compass.demo import DEMO_TODAY, demo_events
from compass.engine.freetime import busy_blocks, day_window, free_gaps, free_minutes
from compass.models import Event

TZ = ZoneInfo("America/Chicago")
MON = DEMO_TODAY.date()            # 2026-11-30
TUE = MON + timedelta(days=1)
FRI = MON + timedelta(days=4)
SAT = MON + timedelta(days=5)

# Fixed here (not read from config.yaml) so editing your config can't break these tests.
CONFIG = Config.model_validate({
    "timezone": "America/Chicago",
    "day_window": {"start": "08:00", "end": "23:00"},
    "protected": [
        {"title": "Dinner", "start": "18:00", "end": "19:00",
         "days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]},
        {"title": "Evening off", "start": "19:00", "end": "21:00", "days": ["fri", "sat"]},
    ],
    "planner": {"min_block_minutes": 25, "max_block_minutes": 90, "break_minutes": 10,
                "daily_cap_minutes": 360},
    "calendars": ["primary"],
    "models": {"writer": "claude-sonnet-5-5"},
})


def at(day: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(day, time(h, m), tzinfo=TZ)


def event(day: date, start: str, end: str, id="gcal:1", end_day: date | None = None, **kw) -> Event:
    return Event(id=id, title=id, start=at(day, start), end=at(end_day or day, end), **kw)


def overlaps(a_start, a_end, b_start, b_end) -> bool:
    return a_start < b_end and b_start < a_end


def test_event_overlapping_protected_time_merges_into_one_block():
    # The demo's Tuesday study group runs 17:30-18:30, across dinner at 18:00-19:00.
    evening = [b for b in busy_blocks(TUE, demo_events(), CONFIG) if b.start >= at(TUE, "17:00")]
    assert len(evening) == 1
    [block] = evening
    assert (block.start, block.end) == (at(TUE, "17:30"), at(TUE, "19:00"))
    assert block.kind == "fixed"
    assert "Dinner" in block.title and "study group" in block.title


@pytest.mark.parametrize("offset", range(14))
def test_gaps_never_overlap_busy_and_stay_in_window(offset):
    day = MON + timedelta(days=offset)
    events = demo_events()
    win_start, win_end = day_window(day, CONFIG)
    gaps = free_gaps(day, events, CONFIG)
    busy = busy_blocks(day, events, CONFIG)
    for gs, ge in gaps:
        assert win_start <= gs < ge <= win_end
        assert not any(overlaps(gs, ge, b.start, b.end) for b in busy)
    # Gaps plus busy time cover the whole window exactly.
    busy_minutes = sum(b.minutes for b in busy)
    assert free_minutes(day, events, CONFIG) + busy_minutes == 15 * 60


def test_gaps_on_demo_monday():
    gaps = free_gaps(MON, demo_events(), CONFIG)
    assert [(s.strftime("%H:%M"), e.strftime("%H:%M")) for s, e in gaps] == [
        ("08:00", "09:00"), ("09:50", "11:00"), ("11:50", "18:00"), ("19:00", "23:00")]


def test_not_before_trims_gap():
    gaps = free_gaps(MON, demo_events(), CONFIG, not_before=at(MON, "10:15"))
    assert gaps[0] == (at(MON, "10:15"), at(MON, "11:00"))
    assert all(s >= at(MON, "10:15") for s, _ in gaps)


def test_not_before_inside_busy_block_and_after_window():
    gaps = free_gaps(MON, demo_events(), CONFIG, not_before=at(MON, "09:20"))
    assert gaps[0][0] == at(MON, "09:50")
    assert free_gaps(MON, [], CONFIG, not_before=at(MON, "23:30")) == []
    # A UTC `not_before` works the same as a local one.
    utc = at(MON, "10:15").astimezone(ZoneInfo("UTC"))
    assert free_gaps(MON, demo_events(), CONFIG, not_before=utc)[0][0] == at(MON, "10:15")


def test_weekend_protected_block_only_on_fri_and_sat():
    def protected(day):
        return [b.title for b in busy_blocks(day, [], CONFIG) if b.kind == "protected"]
    assert protected(FRI) == ["Dinner", "Evening off"]
    assert protected(SAT) == ["Dinner", "Evening off"]
    for day in (MON, TUE, MON + timedelta(days=6)):
        assert protected(day) == ["Dinner"]


def test_touching_blocks_stay_separate():
    # Dinner 18-19 and the Friday block 19-21 touch but don't overlap.
    blocks = busy_blocks(FRI, [], CONFIG)
    assert [(b.start.hour, b.end.hour) for b in blocks] == [(18, 19), (19, 21)]


def test_event_spanning_midnight_counts_on_both_days():
    late = event(MON, "22:00", "01:30", end_day=TUE)
    [mon_block] = [b for b in busy_blocks(MON, [late], CONFIG) if b.kind == "fixed"]
    assert (mon_block.start, mon_block.end) == (at(MON, "22:00"), at(MON, "23:00"))
    # Tuesday's window starts at 08:00, after the event ends, so nothing is blocked.
    assert [b for b in busy_blocks(TUE, [late], CONFIG) if b.kind == "fixed"] == []
    overnight = event(MON, "20:00", "09:00", end_day=TUE)
    [tue_block] = [b for b in busy_blocks(TUE, [overnight], CONFIG) if b.kind == "fixed"]
    assert (tue_block.start, tue_block.end) == (at(TUE, "08:00"), at(TUE, "09:00"))


def test_all_day_events_block_only_when_busy():
    free_all_day = event(MON, "00:00", "00:00", end_day=TUE, all_day=True, busy=False)
    assert free_minutes(MON, [free_all_day], CONFIG) == free_minutes(MON, [], CONFIG)

    trip = event(MON, "00:00", "00:00", id="gcal:trip", end_day=MON + timedelta(days=2),
                 all_day=True, busy=True)
    assert free_gaps(MON, [trip], CONFIG) == []
    assert free_gaps(TUE, [trip], CONFIG) == []
    assert free_gaps(MON + timedelta(days=2), [trip], CONFIG) != []  # end date is exclusive


def test_free_timed_events_never_block():
    tentative = event(MON, "12:00", "13:00", busy=False)
    assert free_minutes(MON, [tentative], CONFIG) == free_minutes(MON, [], CONFIG)


def test_events_on_other_days_ignored():
    assert free_minutes(MON, [event(TUE, "12:00", "13:00")], CONFIG) == free_minutes(MON, [], CONFIG)


def test_utc_events_convert_to_local():
    # 18:00 UTC is 12:00 in Chicago in winter.
    e = Event(id="gcal:1", title="Lunch", start=datetime(2026, 11, 30, 18, 0, tzinfo=ZoneInfo("UTC")),
              end=datetime(2026, 11, 30, 19, 0, tzinfo=ZoneInfo("UTC")))
    [block] = [b for b in busy_blocks(MON, [e], CONFIG) if b.kind == "fixed"]
    assert block.start == at(MON, "12:00") and block.start.tzinfo == TZ


def test_dst_day_minutes():
    # 2027-03-14: clocks jump 02:00 -> 03:00, outside the 08:00-23:00 window, so 15 hours remain.
    assert free_minutes(date(2027, 3, 14), [], CONFIG) == 15 * 60 - 60  # dinner only (a Sunday)


def test_randomized_gaps_are_disjoint_from_busy():
    rng = random.Random(1234)
    for _ in range(200):
        day = MON + timedelta(days=rng.randrange(14))
        events = []
        for i in range(rng.randrange(8)):
            start = at(day, "00:00") + timedelta(minutes=rng.randrange(-300, 1700, 5))
            end = start + timedelta(minutes=rng.randrange(5, 600, 5))
            events.append(Event(id=f"gcal:{i}", title=f"e{i}", start=start, end=end,
                                busy=rng.random() > 0.1, all_day=rng.random() < 0.05))
        busy = busy_blocks(day, events, CONFIG)
        gaps = free_gaps(day, events, CONFIG)
        win_start, win_end = day_window(day, CONFIG)
        for a, b in zip(busy, busy[1:]):
            assert a.end <= b.start  # merged: no overlaps left
        for gs, ge in gaps:
            assert win_start <= gs < ge <= win_end
            assert not any(overlaps(gs, ge, b.start, b.end) for b in busy)
