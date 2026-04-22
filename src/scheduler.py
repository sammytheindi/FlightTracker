"""APScheduler wrapper for automated periodic flight searches and daily reports."""

from __future__ import annotations

import logging
import signal
import sys

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
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


def _twice_daily_cron(job_index: int, total_jobs: int) -> tuple[CronTrigger, str]:
    """
    Return a CronTrigger that fires twice a day, with each job offset so that
    all jobs are spread as evenly as possible across the 24-hour period.

    With N jobs, consecutive search events are spaced 12h/N apart.

    Example spreads:
      1 job:  00:00 & 12:00
      2 jobs: 00:00 & 12:00 / 06:00 & 18:00
      3 jobs: 00:00 & 12:00 / 04:00 & 16:00 / 08:00 & 20:00

    Returns:
        (CronTrigger, "HH:MM & HH:MM") display string.
    """
    offset_minutes = (job_index * 720) // total_jobs  # 720 = 12h in minutes
    hour1, minute = divmod(offset_minutes, 60)
    hour2 = (hour1 + 12) % 24

    trigger = CronTrigger(hour=f"{hour1},{hour2}", minute=minute)
    display = f"{hour1:02d}:{minute:02d} & {hour2:02d}:{minute:02d}"
    return trigger, display


def start_watch(
    config: AppConfig,
    adapter: FlightSearchAdapter,
    db: Database,
    interval: str = "12h",
) -> None:
    """
    Run flight searches on a recurring schedule until interrupted.
    Convenience wrapper around start_watch_multi for single-config use.
    """
    start_watch_multi(configs=[config], db=db, interval=interval)


def start_watch_multi(
    configs: list[AppConfig],
    db: Database,
    interval: str = "12h",
) -> None:
    """
    Run flight searches and daily report emails for multiple job configs.

    Each config gets:
      - A search job: twice daily by default (CronTrigger), spread evenly across
        the day so all jobs don't fire at once. Pass a custom interval (e.g. "1m",
        "6h") to override with an IntervalTrigger instead (useful for testing).
      - A CronTrigger daily report job (at config.report.send_time).

    Args:
        configs: List of loaded AppConfig objects (one per job file).
        db: Shared Database instance for all jobs.
        interval: "12h" (default) → twice-daily CronTrigger spread across jobs.
                  Any other value → IntervalTrigger at that cadence.
    """
    use_spread = interval.strip().lower() == "12h"
    scheduler = BlockingScheduler()

    for i, config in enumerate(configs):
        route_label = "/".join(
            f"{o}→{d}"
            for o in config.search.origins
            for d in config.search.destinations
        )

        # --- Search job ---
        def _make_search_job(cfg: AppConfig, label: str):
            def job() -> None:
                from src.api.google_flights import GoogleFlightsAdapter

                console.rule(f"[bold cyan]Scheduled search:[/] {label}")
                fresh_adapter = GoogleFlightsAdapter()
                try:
                    results = run_search(cfg, fresh_adapter, db)
                finally:
                    fresh_adapter.close()
                deals = check_and_alert(results, cfg.alerts)
                if deals:
                    console.print(
                        f"[bold green]{len(deals)} deal(s)[/] below "
                        f"${cfg.alerts.threshold_usd:.0f}/person — alert sent."
                    )

            return job

        if use_spread:
            search_trigger, time_display = _twice_daily_cron(i, len(configs))
        else:
            search_trigger = IntervalTrigger(**parse_interval(interval))
            time_display = f"every {interval}"

        scheduler.add_job(
            _make_search_job(config, route_label),
            trigger=search_trigger,
            id=f"search_{i}",
            replace_existing=True,
            max_instances=1,
        )

        # --- Daily report job ---
        def _make_report_job(cfg: AppConfig, label: str):
            def job() -> None:
                from src.report import send_daily_report

                console.rule(f"[bold blue]Daily report:[/] {label}")
                try:
                    send_daily_report(cfg, str(db._path))
                    console.print(f"[dim]Report email sent for {label}.[/]")
                except Exception as e:
                    logger.error("Failed to send daily report for %s: %s", label, e)
                    console.print(f"[red]Report failed for {label}:[/] {e}")

            return job

        rep_hour, rep_minute = map(int, config.report.send_time.split(":"))
        scheduler.add_job(
            _make_report_job(config, route_label),
            trigger=CronTrigger(hour=rep_hour, minute=rep_minute),
            id=f"report_{i}",
            replace_existing=True,
            max_instances=1,
        )

    # Print status table
    console.print(f"[bold]Watch mode started[/] — {len(configs)} job(s). Press Ctrl+C to stop.\n")
    for i, config in enumerate(configs):
        route_label = "/".join(
            f"{o}→{d}"
            for o in config.search.origins
            for d in config.search.destinations
        )
        if use_spread:
            _, time_display = _twice_daily_cron(i, len(configs))
            schedule_str = f"search at {time_display}"
        else:
            schedule_str = f"search every {interval}"
        console.print(
            f"  [cyan]{route_label}[/]  {schedule_str},"
            f" report daily at {config.report.send_time}"
        )

    console.print()

    # Run all searches immediately on startup
    for i in range(len(configs)):
        scheduler.get_job(f"search_{i}").func()

    def _shutdown(sig, frame):
        console.print("\n[yellow]Stopping watch mode...[/]")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    scheduler.start()
