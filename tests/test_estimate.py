import sqlite3
from datetime import timedelta

import pytest

from compass.demo import DEMO_TODAY, demo_tasks
from compass.engine.estimate import (
    DEFAULT_MINUTES, KEYWORDS, MAX_POINTS_FACTOR, auto_estimates, base_minutes,
    course_medians, estimate_minutes,
)
from compass.engine.merge import merge_tasks
from compass.models import Task
from compass.orchestrator import apply_estimates
from compass.store import SCHEMA, Store

NOW = DEMO_TODAY
WINDOW = (NOW - timedelta(days=7), NOW + timedelta(days=14))


def task(title="Problem Set 1", points=10.0, course="MATH", id="demo:1") -> Task:
    return Task(id=id, title=title, source="demo", course=course, points=points)


def demo_store() -> Store:
    store = Store(":memory:")
    merge_tasks(store, "demo", demo_tasks(), NOW, WINDOW)
    return store


@pytest.mark.parametrize("word, minutes", sorted(KEYWORDS.items()))
def test_each_keyword_maps_to_its_base(word, minutes):
    assert base_minutes(f"{word.title()} 3") == minutes
    assert estimate_minutes(task(f"Week 2 {word}"), course_median_points=10) == minutes


def test_no_keyword_gives_default():
    assert base_minutes("Problem Set 7") == DEFAULT_MINUTES


def test_keyword_matching_rules():
    assert base_minutes("Reading Quiz 4") == KEYWORDS["quiz"]           # last word in head wins
    assert base_minutes("Discussion Post: Essay prompt") == KEYWORDS["post"]  # head beats tail
    assert base_minutes("Week 3: Lab") == KEYWORDS["lab"]              # tail if head has none
    assert base_minutes("Pre-lab questions") == KEYWORDS["lab"]
    assert base_minutes("Two Quizzes") == KEYWORDS["quiz"]              # plurals
    assert base_minutes("Labels and examples") == DEFAULT_MINUTES       # whole words only


def test_points_scaling():
    assert estimate_minutes(task("Lab 1", points=10), 10) == 120        # at median
    assert estimate_minutes(task("Lab 1", points=5), 10) == 120         # below never shrinks
    assert estimate_minutes(task("Lab 1", points=15), 10) == 180        # 1.5x
    assert estimate_minutes(task("Lab 1", points=10), 0) == 120         # no median


def test_points_scaling_capped():
    capped = KEYWORDS["project"] * MAX_POINTS_FACTOR
    assert estimate_minutes(task("Final Project", points=1000), 10) == capped
    assert estimate_minutes(task("Final Project", points=20), 10) == capped


@pytest.mark.parametrize("points", [0, 1, 7, 11, 13, 17, 19, 23, 99])
def test_results_are_multiples_of_5(points):
    for title in ("Quiz", "Essay", "Problem Set", "Post"):
        minutes = estimate_minutes(task(title, points=points), course_median_points=7)
        assert minutes % 5 == 0 and minutes >= 5


def test_course_medians_ignore_zero_points():
    tasks = [task(points=0, id="a"), task(points=10, id="b"), task(points=30, id="c"),
             task(points=50, course="BIO", id="d")]
    assert course_medians(tasks) == {"MATH": 20, "BIO": 50}


def test_auto_estimates_skip_overridden():
    tasks = [task(id="a"), task(id="b")]
    assert set(auto_estimates(tasks, {"a"})) == {"b"}


def test_apply_estimates_sets_demo_tasks():
    store = demo_store()
    assert apply_estimates(store) == len(demo_tasks())
    by_id = {t.id: t.est_minutes for t in store.get_tasks()}
    assert by_id["demo:108"] == 480   # 240-minute essay, 100 pts vs a HIST median of 10: 2x cap
    assert by_id["demo:105"] == 60    # 5-pt reading, below median: no scaling
    assert by_id["demo:110"] == 520   # 300-minute project, 200 pts vs a CS median of 115: 1.74x
    assert all(m > 0 and m % 5 == 0 for m in by_id.values())


def test_apply_estimates_leaves_override_alone():
    store = demo_store()
    store.set_estimate("demo:110", 45, NOW)
    assert apply_estimates(store) == len(demo_tasks()) - 1
    assert next(t for t in store.get_tasks() if t.id == "demo:110").est_minutes == 45
    # The automatic value sits underneath, untouched by the override.
    raw = store.db.execute("SELECT est_minutes FROM tasks WHERE id='demo:110'").fetchone()[0]
    assert raw == 0


def test_estimates_survive_a_merge():
    store = demo_store()
    apply_estimates(store)
    before = {t.id: t.est_minutes for t in store.get_tasks()}
    merge_tasks(store, "demo", demo_tasks(), NOW, WINDOW)
    assert {t.id: t.est_minutes for t in store.get_tasks()} == before


def test_latest_override_wins():
    store = demo_store()
    store.set_estimate("demo:110", 45, NOW)
    store.set_estimate("demo:110", 90, NOW + timedelta(minutes=1))
    assert store.get_overrides() == {"demo:110": 90}
    assert store.db.execute("SELECT count(*) FROM estimate_overrides").fetchone()[0] == 2


def test_set_estimate_rejects_bad_input():
    store = demo_store()
    with pytest.raises(KeyError):
        store.set_estimate("demo:nope", 30, NOW)
    with pytest.raises(ValueError):
        store.set_estimate("demo:110", -5, NOW)


def test_old_est_override_values_migrate(tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript(SCHEMA)
    old.execute("INSERT INTO tasks VALUES"
                " ('canvas:9', 'Essay', 'canvas', '', NULL, 0, 0, 200, 0, 0, '')")
    old.commit()
    old.close()

    store = Store(str(path))
    assert store.get_overrides() == {"canvas:9": 200}
    store.set_estimate("canvas:9", 150, NOW)  # any new override beats a migrated one
    assert store.get_tasks()[0].est_minutes == 150
