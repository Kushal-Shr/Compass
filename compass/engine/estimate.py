"""Guess how many minutes a task needs, from words in its title and its points.

Pure functions: the store reads and writes happen in `orchestrator.apply_estimates`.
Later phases learn from logged time; this table is the starting point.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from collections.abc import Collection, Iterable

from ..models import Task

# Base minutes for a word in the title. "exam" and "midterm" mean study time.
KEYWORDS: dict[str, int] = {
    "essay": 240, "paper": 240,
    "project": 300,
    "lab": 120,
    "quiz": 45,
    "exam": 180, "midterm": 180,
    "reading": 60,
    "discussion": 30, "post": 30,
}
DEFAULT_MINUTES = 60
MAX_POINTS_FACTOR = 2.0

_PLURALS = {"quizzes": "quiz"}
_WORD = re.compile(r"[a-z]+")


def _keyword(word: str) -> str | None:
    word = _PLURALS.get(word, word)
    if word in KEYWORDS:
        return word
    if word.endswith("s") and word[:-1] in KEYWORDS:
        return word[:-1]
    return None


def base_minutes(title: str) -> int:
    """Minutes for the title's keyword, or the default.

    The head of the title (before any ":") decides, and within it the last keyword wins,
    because the last noun names the thing: "Reading Quiz" is a quiz, "Lab Report" is a lab,
    "Discussion Post: Essay prompt" is a post. If the head has no keyword, the rest is tried.
    """
    head = title.split(":", 1)[0]
    for part in (head, title):
        for word in reversed(_WORD.findall(part.lower())):
            if keyword := _keyword(word):
                return KEYWORDS[keyword]
    return DEFAULT_MINUTES


def points_factor(points: float, course_median_points: float) -> float:
    """1.0 at or below the course median, rising with points, capped at MAX_POINTS_FACTOR."""
    if course_median_points <= 0 or points <= course_median_points:
        return 1.0
    return min(points / course_median_points, MAX_POINTS_FACTOR)


def _round5(minutes: float) -> int:
    return max(5, int(math.floor(minutes / 5 + 0.5)) * 5)


def estimate_minutes(task: Task, course_median_points: float) -> int:
    """Estimated minutes, a multiple of 5 and at least 5."""
    return _round5(base_minutes(task.title) * points_factor(task.points, course_median_points))


def course_medians(tasks: Iterable[Task]) -> dict[str, float]:
    """Median points per course, ignoring ungraded (0-point) tasks so they don't drag it down."""
    points: dict[str, list[float]] = defaultdict(list)
    for t in tasks:
        if t.points > 0:
            points[t.course].append(t.points)
    return {course: statistics.median(values) for course, values in points.items()}


def auto_estimates(tasks: list[Task], overridden: Collection[str]) -> dict[str, int]:
    """Automatic estimate for every task whose ID isn't in `overridden`.

    Medians use every task in the course, including overridden ones.
    """
    medians = course_medians(tasks)
    return {t.id: estimate_minutes(t, medians.get(t.course, 0.0))
            for t in tasks if t.id not in overridden}
