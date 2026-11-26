"""Settings. The only module that reads `config.yaml`, `.env` or environment variables.

Entry points call `load_config()` and `load_env()` once and pass the results down.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from datetime import time
from pathlib import Path
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, SecretStr, field_validator, model_validator

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]

_HHMM = re.compile(r"^\d{2}:\d{2}$")


def _parse_hhmm(value: object) -> time:
    # PyYAML reads an unquoted 18:00 as the integer 1080 (base 60), so only quoted
    # "HH:MM" strings are accepted. Anything else would silently become the wrong time.
    if isinstance(value, time):
        return value
    if not isinstance(value, str) or not _HHMM.match(value):
        raise ValueError(f'expected a quoted "HH:MM" time, got {value!r}')
    hour, minute = (int(part) for part in value.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError(f"not a valid time: {value!r}")
    return time(hour, minute)


HHMM = Annotated[time, BeforeValidator(_parse_hhmm)]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DayWindow(_Section):
    start: HHMM
    end: HHMM

    @model_validator(mode="after")
    def _start_before_end(self) -> DayWindow:
        if self.start >= self.end:
            raise ValueError("day_window start must be before end")
        return self


class Protected(_Section):
    title: str
    start: HHMM
    end: HHMM
    days: list[Weekday] = Field(min_length=1)

    @model_validator(mode="after")
    def _start_before_end(self) -> Protected:
        if self.start >= self.end:
            raise ValueError(f"protected time {self.title!r}: start must be before end")
        return self


class Planner(_Section):
    min_block_minutes: int = Field(gt=0)
    max_block_minutes: int = Field(gt=0)
    break_minutes: int = Field(ge=0)
    daily_cap_minutes: int = Field(gt=0)

    @model_validator(mode="after")
    def _min_not_above_max(self) -> Planner:
        if self.min_block_minutes > self.max_block_minutes:
            raise ValueError("planner min_block_minutes must not exceed max_block_minutes")
        return self


class Config(_Section):
    timezone: str
    day_window: DayWindow
    protected: list[Protected] = []
    planner: Planner
    calendars: list[str] = Field(min_length=1)
    models: dict[str, str]  # agent name -> model ID

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone: {value!r}") from exc
        return value

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


def load_config(path: str | Path = "config.yaml") -> Config:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return Config.model_validate(data)


class Secrets(BaseModel):
    """Credentials and account settings. Never printed: `repr` shows only which fields are set."""

    model_config = ConfigDict(frozen=True)

    canvas_base_url: str | None = None
    canvas_token: SecretStr | None = None
    google_client_file: str | None = None
    anthropic_api_key: SecretStr | None = None

    def __repr__(self) -> str:
        fields = ", ".join(
            f"{name}={'set' if getattr(self, name) is not None else 'unset'}"
            for name in type(self).model_fields
        )
        return f"Secrets({fields})"

    __str__ = __repr__


_ENV_KEYS = {
    "CANVAS_BASE_URL": "canvas_base_url",
    "CANVAS_TOKEN": "canvas_token",
    "GOOGLE_CLIENT_FILE": "google_client_file",
    "ANTHROPIC_API_KEY": "anthropic_api_key",
}


def load_env(path: str | Path = ".env", environ: Mapping[str, str] | None = None) -> Secrets:
    """Read `.env` (if present), then let real environment variables override it.

    Environment variables win so that GitHub Actions and server secrets work without a `.env`.
    Empty values count as unset. `environ` defaults to `os.environ` and exists for tests.
    """
    values: dict[str, str | None] = dict(dotenv_values(path)) if Path(path).is_file() else {}
    values.update(os.environ if environ is None else environ)
    return Secrets(**{
        field: value
        for key, field in _ENV_KEYS.items()
        if (value := (values.get(key) or "").strip())
    })
