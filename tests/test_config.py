"""Tests for src/config.py."""

import textwrap
from pathlib import Path

import pytest
import yaml

from src.config import load_config, AppConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def write_config(tmp_path: Path, content: dict) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(yaml.dump(content))
    return p


VALID_CONFIG = {
    "api": {
        "provider": "google_flights",
    },
    "search": {
        "origins": ["DFW", "DAL"],
        "destinations": ["AMD"],
        "depart_dates": {"start": "2026-12-10", "end": "2026-12-20"},
        "return_dates": {"start": "2027-01-01", "end": "2027-01-10"},
        "passengers": 2,
        "cabin_class": "ECONOMY",
        "rate_limit_delay": 0.5,
        "max_results_per_search": 5,
    },
    "alerts": {
        "enabled": False,
        "threshold_usd": 1200,
    },
}


# ---------------------------------------------------------------------------
# Valid config
# ---------------------------------------------------------------------------


def test_load_valid_config(tmp_path):
    path = write_config(tmp_path, VALID_CONFIG)
    config = load_config(path)

    assert isinstance(config, AppConfig)
    assert config.api.provider == "google_flights"
    assert config.search.origins == ["DFW", "DAL"]
    assert config.search.destinations == ["AMD"]
    assert config.search.passengers == 2
    assert config.search.cabin_class == "ECONOMY"
    assert config.alerts.enabled is False


def test_depart_dates_range(tmp_path):
    path = write_config(tmp_path, VALID_CONFIG)
    config = load_config(path)

    dates = config.search.depart_dates.dates()
    assert len(dates) == 11  # Dec 10 through Dec 20 inclusive
    assert str(dates[0]) == "2026-12-10"
    assert str(dates[-1]) == "2026-12-20"


def test_return_dates_range(tmp_path):
    path = write_config(tmp_path, VALID_CONFIG)
    config = load_config(path)

    dates = config.search.return_dates.dates()
    assert len(dates) == 10  # Jan 1 through Jan 10 inclusive
    assert str(dates[0]) == "2027-01-01"
    assert str(dates[-1]) == "2027-01-10"


def test_airport_codes_uppercased(tmp_path):
    raw = dict(VALID_CONFIG)
    raw["search"] = dict(raw["search"], origins=["dfw", "dal"], destinations=["amd"])
    path = write_config(tmp_path, raw)
    config = load_config(path)

    assert config.search.origins == ["DFW", "DAL"]
    assert config.search.destinations == ["AMD"]


# ---------------------------------------------------------------------------
# File not found
# ---------------------------------------------------------------------------


def test_missing_config_file():
    with pytest.raises(FileNotFoundError, match="config.yaml"):
        load_config("/nonexistent/path/config.yaml")


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


def test_missing_api_provider(tmp_path):
    raw = {k: v for k, v in VALID_CONFIG.items()}
    raw["api"] = {}
    path = write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="provider"):
        load_config(path)


def test_missing_search_origins(tmp_path):
    raw = dict(VALID_CONFIG)
    raw["search"] = {k: v for k, v in raw["search"].items() if k != "origins"}
    path = write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="origins"):
        load_config(path)


def test_missing_passengers(tmp_path):
    raw = dict(VALID_CONFIG)
    raw["search"] = {k: v for k, v in raw["search"].items() if k != "passengers"}
    path = write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="passengers"):
        load_config(path)


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_invalid_provider(tmp_path):
    raw = dict(VALID_CONFIG)
    raw["api"] = {"provider": "amadeus"}
    path = write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="provider"):
        load_config(path)


def test_invalid_cabin_class(tmp_path):
    raw = dict(VALID_CONFIG)
    raw["search"] = dict(raw["search"], cabin_class="LUXURY")
    path = write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="cabin_class"):
        load_config(path)


def test_end_before_start(tmp_path):
    raw = dict(VALID_CONFIG)
    raw["search"] = dict(
        raw["search"],
        depart_dates={"start": "2026-12-20", "end": "2026-12-10"},
    )
    path = write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="end date"):
        load_config(path)


def test_zero_passengers(tmp_path):
    raw = dict(VALID_CONFIG)
    raw["search"] = dict(raw["search"], passengers=0)
    path = write_config(tmp_path, raw)

    with pytest.raises(ValueError, match="passengers"):
        load_config(path)


# ---------------------------------------------------------------------------
# Alerts with email
# ---------------------------------------------------------------------------


def test_alerts_with_email(tmp_path):
    raw = dict(VALID_CONFIG)
    raw["alerts"] = {
        "enabled": True,
        "threshold_usd": 1000,
        "email": {
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "sender": "a@b.com",
            "password": "secret",
            "recipients": ["a@b.com"],
        },
    }
    path = write_config(tmp_path, raw)
    config = load_config(path)

    assert config.alerts.enabled is True
    assert config.alerts.threshold_usd == 1000
    assert config.alerts.email is not None
    assert config.alerts.email.smtp_host == "smtp.gmail.com"
    assert config.alerts.email.recipients == ["a@b.com"]
