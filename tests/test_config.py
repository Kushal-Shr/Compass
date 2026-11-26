from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml
from pydantic import ValidationError

from compass.config import Config, Secrets, load_config, load_env

REPO_ROOT = Path(__file__).resolve().parent.parent


def _base() -> dict:
    return {
        "timezone": "America/Chicago",
        "day_window": {"start": "08:00", "end": "23:00"},
        "protected": [{"title": "Dinner", "start": "18:00", "end": "19:00", "days": ["mon"]}],
        "planner": {
            "min_block_minutes": 25,
            "max_block_minutes": 90,
            "break_minutes": 10,
            "daily_cap_minutes": 360,
        },
        "calendars": ["primary"],
        "models": {"writer": "claude-sonnet-5-5"},
    }


def test_real_config_loads():
    config = load_config(REPO_ROOT / "config.yaml")
    assert config.tz == ZoneInfo("America/Chicago")
    assert isinstance(config.day_window.start, time)
    assert config.day_window.start < config.day_window.end
    assert config.protected
    for block in config.protected:
        assert isinstance(block.start, time)
        assert set(block.days) <= {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
    assert config.calendars
    assert "writer" in config.models


def test_times_parse():
    config = Config.model_validate(_base())
    assert config.day_window.start == time(8, 0)
    assert config.protected[0].end == time(19, 0)


def test_bad_time_rejected():
    data = _base()
    data["day_window"]["end"] = "25:00"
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_unknown_weekday_rejected():
    data = _base()
    data["protected"][0]["days"] = ["mon", "funday"]
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_unquoted_yaml_time_rejected(tmp_path):
    # PyYAML turns an unquoted 18:00 into the integer 1080; that must not load as 00:18.
    text = yaml.safe_dump(_base()).replace("'18:00'", "18:00")
    assert "start: 18:00" in text
    path = tmp_path / "config.yaml"
    path.write_text(text)
    with pytest.raises(ValidationError):
        load_config(path)


def test_unknown_timezone_rejected():
    data = _base()
    data["timezone"] = "Mars/Olympus_Mons"
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_unknown_key_rejected():
    data = _base()
    data["planner"]["max_block_minuts"] = 60
    with pytest.raises(ValidationError):
        Config.model_validate(data)


def test_secrets_repr_hides_values():
    secrets = Secrets(
        canvas_base_url="https://school.example.edu",
        canvas_token="fakefakefakefake",
        google_client_file="client_secret_abc.json",
        anthropic_api_key="dummydummydummy",
    )
    for shown in (repr(secrets), str(secrets), f"{secrets}"):
        assert "fakefakefakefake" not in shown
        assert "dummydummydummy" not in shown
        assert "school.example.edu" not in shown
        assert "canvas_token=set" in shown
    assert secrets.canvas_token.get_secret_value() == "fakefakefakefake"


def test_load_env_reads_file_and_env_overrides(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CANVAS_BASE_URL=https://school.example.edu\n"
        "CANVAS_TOKEN=from-file\n"
        "GOOGLE_CLIENT_FILE=\n"
    )
    secrets = load_env(env_file, environ={"CANVAS_TOKEN": "from-env"})
    assert secrets.canvas_base_url == "https://school.example.edu"
    assert secrets.canvas_token.get_secret_value() == "from-env"
    assert secrets.google_client_file is None  # empty counts as unset
    assert secrets.anthropic_api_key is None


def test_load_env_without_file(tmp_path):
    secrets = load_env(tmp_path / "missing.env", environ={})
    assert secrets == Secrets()
