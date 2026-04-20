"""APScheduler wrapper for automated periodic flight searches."""

from __future__ import annotations

import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from rich.console import Console

from src.alerts import check_and_alert
from src.api.base import FlightSearchAdapter
from src.config import AppConfig
from src.db import Database
from src.search import run_search

logger = logging.getLogger(__name__)
console = Console()


def parse_interval(interval_str: str) -> dict:
    """
    Parse a human-readable interval string into APScheduler kwargs.

    Supported formats: "30m", "2h", "1d"

    Returns:
        Dict suitable for IntervalTrigger(**kwargs).

    Raises:
        ValueError: for unrecognized formats.
    """
    interval_str = interval_str.strip().lower()
    if interval_str.endswith("m"):
        return {"minutes": int(interval_str[:-1])}
    elif interval_str.endswith("h"):
        return {"hours": int(interval_str[:-1])}
    elif interval_str.endswith("d"):
        return {"days": int(interval_str[:-1])}
    else:
        raise ValueError(
            f"Unrecognized interval '{interval_str}'. Use formats like '30m', '2h', or '1d'."
        )


def start_watch(
    config: AppConfig,
    adapter: FlightSearchAdapter,
    db: Database,
    interval: str = "6h",
) -> None:
    """
    Run flight searches on a recurring schedule until interrupted.

    Args:
        config: Loaded application config.
        adapter: Flight search adapter to use.
        db: Database for persisting results.
        interval: Interval between searches (e.g. "30m", "6h", "1d").
    """
    interval_kwargs = parse_interval(interval)

    def job() -> None:
        console.rule(f"[bold cyan]Scheduled search[/]")
        fresh_adapter = adapter.__class__()
        try:
            results = run_search(config, fresh_adapter, db)
        finally:
            fresh_adapter.close()
        deals = check_and_alert(results, config.alerts)
        if deals:
            console.print(
                f"[bold green]{len(deals)} deal(s)[/] found below "
                f"${config.alerts.threshold_usd:.0f}/person — alert sent."
            )

    scheduler = BlockingScheduler()
    scheduler.add_job(
        job,
        trigger=IntervalTrigger(**interval_kwargs),
        id="flight_search",
        replace_existing=True,
        max_instances=1,  # prevent overlapping runs
    )

    # Run once immediately, then on schedule
    console.print(f"[bold]Watch mode started[/] — running every {interval}. Press Ctrl+C to stop.")
    job()

    def _shutdown(sig, frame):
        console.print("\n[yellow]Stopping watch mode...[/]")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    scheduler.start()
