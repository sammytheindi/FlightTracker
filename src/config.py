"""Configuration loading and validation from config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import yaml


# ---------------------------------------------------------------------------
# Typed config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ApiConfig:
    provider: str


@dataclass
class DateRange:
    start: date
    end: date

    def dates(self) -> list[date]:
        """Return every date in the range (inclusive)."""
        result: list[date] = []
        current = self.start
        while current <= self.end:
            result.append(current)
            current += timedelta(days=1)
        return result


@dataclass
class SearchConfig:
    origins: list[str]
    destinations: list[str]
    depart_dates: DateRange
    return_dates: DateRange
    passengers: int
    cabin_class: str
    rate_limit_delay: float
    max_results_per_search: int


@dataclass
class EmailConfig:
    smtp_host: str
    smtp_port: int
    sender: str
    password: str
    recipients: list[str]


@dataclass
class AlertsConfig:
    enabled: bool
    threshold_usd: float
    email: Optional[EmailConfig]


@dataclass
class ReportConfig:
    days: int = 14
    send_time: str = "07:00"


@dataclass
class AppConfig:
    api: ApiConfig
    search: SearchConfig
    alerts: AlertsConfig
    report: ReportConfig = field(default_factory=ReportConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def load_config(config_path: str | Path = "config.yaml") -> AppConfig:
    """
    Load and validate config.yaml.

    Raises:
        FileNotFoundError: if config_path does not exist.
        ValueError: if required fields are missing or invalid.
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            "Copy config.example.yaml to config.yaml and fill in your values."
        )

    with path.open() as f:
        raw = yaml.safe_load(f)

    return _parse(raw)


def _parse(raw: dict) -> AppConfig:
    _require(raw, "api")
    _require(raw, "search")
    _require(raw, "alerts")

    api = _parse_api(raw["api"])
    search = _parse_search(raw["search"])
    alerts = _parse_alerts(raw["alerts"])
    report = _parse_report(raw.get("report") or {})

    return AppConfig(api=api, search=search, alerts=alerts, report=report)


def _parse_api(raw: dict) -> ApiConfig:
    _require(raw, "provider", section="api")

    provider = raw["provider"]
    if provider not in {"google_flights"}:
        raise ValueError(f"api.provider must be 'google_flights'; got '{provider}'")

    return ApiConfig(provider=provider)


def _parse_search(raw: dict) -> SearchConfig:
    for key in ("origins", "destinations", "depart_dates", "return_dates", "passengers"):
        _require(raw, key, section="search")

    origins = [str(o).upper() for o in raw["origins"]]
    destinations = [str(d).upper() for d in raw["destinations"]]

    if not origins:
        raise ValueError("search.origins must have at least one airport code")
    if not destinations:
        raise ValueError("search.destinations must have at least one airport code")

    depart_dates = _parse_date_range(raw["depart_dates"], "search.depart_dates")
    return_dates = _parse_date_range(raw["return_dates"], "search.return_dates")

    passengers = int(raw["passengers"])
    if passengers < 1:
        raise ValueError("search.passengers must be at least 1")

    cabin_class = str(raw.get("cabin_class", "ECONOMY")).upper()
    valid_cabins = {"ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"}
    if cabin_class not in valid_cabins:
        raise ValueError(f"search.cabin_class must be one of {valid_cabins}")

    return SearchConfig(
        origins=origins,
        destinations=destinations,
        depart_dates=depart_dates,
        return_dates=return_dates,
        passengers=passengers,
        cabin_class=cabin_class,
        rate_limit_delay=float(raw.get("rate_limit_delay", 0.5)),
        max_results_per_search=int(raw.get("max_results_per_search", 5)),
    )


def _parse_date_range(raw: dict, section: str) -> DateRange:
    _require(raw, "start", section=section)
    _require(raw, "end", section=section)
    try:
        start = date.fromisoformat(str(raw["start"]))
        end = date.fromisoformat(str(raw["end"]))
    except ValueError as e:
        raise ValueError(f"{section}: invalid date format — {e}")

    if end < start:
        raise ValueError(f"{section}: end date must be >= start date")

    return DateRange(start=start, end=end)


def _parse_alerts(raw: dict) -> AlertsConfig:
    enabled = bool(raw.get("enabled", False))
    threshold_usd = float(raw.get("threshold_usd", 0))
    email_raw = raw.get("email")

    email: Optional[EmailConfig] = None
    if email_raw:
        for key in ("smtp_host", "smtp_port", "sender", "password", "recipients"):
            _require(email_raw, key, section="alerts.email")
        email = EmailConfig(
            smtp_host=str(email_raw["smtp_host"]),
            smtp_port=int(email_raw["smtp_port"]),
            sender=str(email_raw["sender"]),
            password=str(email_raw["password"]),
            recipients=[str(r) for r in email_raw["recipients"]],
        )

    return AlertsConfig(enabled=enabled, threshold_usd=threshold_usd, email=email)


def _parse_report(raw: dict) -> ReportConfig:
    days = int(raw.get("days", 14))
    if days < 1:
        raise ValueError("report.days must be at least 1")

    send_time = str(raw.get("send_time", "07:00"))
    try:
        hour, minute = send_time.split(":")
        if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
            raise ValueError()
    except (ValueError, AttributeError):
        raise ValueError(
            f"report.send_time must be in HH:MM format (24h), got '{send_time}'"
        )

    return ReportConfig(days=days, send_time=send_time)


def _require(d: dict, key: str, section: str = "root") -> None:
    if key not in d or d[key] is None:
        raise ValueError(f"Missing required config field '{key}' in section '{section}'")
