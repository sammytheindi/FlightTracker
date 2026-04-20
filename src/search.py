"""Multi-route, multi-date flight search orchestrator."""

from __future__ import annotations

import time
from itertools import product

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
from rich import box

from src.api.base import FlightResult, FlightSearchAdapter
from src.config import AppConfig
from src.db import Database

console = Console()


def run_search(
    config: AppConfig,
    adapter: FlightSearchAdapter,
    db: Database,
    verbose: bool = False,
) -> list[FlightResult]:
    """
    Search all combinations of origin × destination × depart_date × return_date.

    Stores every result in the database and returns all results found.
    Fires no alerts — caller is responsible for alert logic.
    """
    depart_dates = [d.isoformat() for d in config.search.depart_dates.dates()]
    return_dates = [d.isoformat() for d in config.search.return_dates.dates()]

    combos = list(
        product(
            config.search.origins,
            config.search.destinations,
            depart_dates,
            return_dates,
        )
    )

    total = len(combos)
    all_results: list[FlightResult] = []
    run_start = time.monotonic()

    console.print(
        f"[bold cyan]Searching {total} combinations[/] "
        f"({len(config.search.origins)} origin(s) × "
        f"{len(config.search.destinations)} destination(s) × "
        f"{len(depart_dates)} depart dates × "
        f"{len(return_dates)} return dates)"
    )

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TextColumn("[dim]{task.fields[status]}"),
        console=console,
        transient=not verbose,  # keep lines visible in verbose mode
    ) as progress:
        task = progress.add_task("Fetching flights...", total=total, status="")

        for origin, destination, depart_date, return_date in combos:
            progress.update(
                task,
                description=f"[cyan]{origin}→{destination}[/] dep [green]{depart_date}[/] ret [yellow]{return_date}[/]",
                status="",
            )

            fetch_start = time.monotonic()
            results = adapter.search(
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                return_date=return_date,
                passengers=config.search.passengers,
                cabin_class=config.search.cabin_class,
                max_results=config.search.max_results_per_search,
            )
            fetch_elapsed = time.monotonic() - fetch_start

            if results:
                db.insert_results(results)
                all_results.extend(results)
                cheapest = min(results, key=lambda r: r.price_per_person)
                status = (
                    f"[green]✓ {len(results)} offers[/] "
                    f"from [bold]${cheapest.price_per_person:.0f}[/] "
                    f"[dim]({fetch_elapsed:.1f}s)[/]"
                )
            else:
                status = f"[yellow]— no results[/] [dim]({fetch_elapsed:.1f}s)[/]"

            if verbose:
                progress.update(task, status=status)

            progress.advance(task)

            if config.search.rate_limit_delay > 0:
                time.sleep(config.search.rate_limit_delay)

    run_elapsed = time.monotonic() - run_start
    _print_summary(all_results, total, run_elapsed, verbose, adapter)
    return all_results


def _print_summary(
    results: list[FlightResult],
    total_combos: int,
    elapsed_s: float,
    verbose: bool,
    adapter: FlightSearchAdapter,
) -> None:
    """Print a summary after a search run."""
    if not results:
        console.print("[yellow]No results returned for any combination.[/]")
        return

    cheapest = min(results, key=lambda r: r.price_per_person)
    priciest = max(results, key=lambda r: r.price_per_person)

    console.print(
        f"\n[bold green]Search complete.[/] "
        f"{len(results)} offers across {total_combos} combos "
        f"[dim]({elapsed_s:.0f}s total)[/]"
    )
    console.print(f"  [green]Cheapest:[/]  {cheapest}")
    console.print(f"  [red]Priciest:[/]  {priciest}")

    if verbose:
        _print_browser_stats(adapter)

    console.print()


def _print_browser_stats(adapter: FlightSearchAdapter) -> None:
    """Print browser session telemetry if the adapter exposes it."""
    # Access the session stats if this is a GoogleFlightsAdapter
    session = getattr(adapter, "_session", None)
    if session is None:
        return
    stats = getattr(session, "stats", None)
    if stats is None:
        return

    table = Table(
        title="Browser Session Telemetry",
        box=box.SIMPLE,
        show_header=False,
        padding=(0, 2),
    )
    table.add_column("Metric", style="bold cyan")
    table.add_column("Value")

    table.add_row("Pages fetched",    str(stats.fetches_done))
    table.add_row("With results",     f"[green]{stats.fetches_succeeded}[/]")
    table.add_row("Empty / blocked",  f"[yellow]{stats.fetches_empty}[/]")
    table.add_row("Errors",           f"[red]{stats.fetches_failed}[/]")
    table.add_row("Success rate",     f"{stats.success_rate:.0f}%")
    table.add_row("Avg page load",    f"{stats.avg_elapsed_s:.1f}s")
    table.add_row("Total fetch time", f"{stats.total_elapsed_s:.0f}s")

    console.print()
    console.print(table)
