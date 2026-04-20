#!/usr/bin/env python3
"""FlightTracker CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path

import logging

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rich import box

console = Console()


def _load_config(config_path: str):
    """Load config and exit with a friendly message on error."""
    from src.config import load_config

    try:
        return load_config(config_path)
    except FileNotFoundError as e:
        console.print(f"[red]Error:[/] {e}")
        sys.exit(1)
    except ValueError as e:
        console.print(f"[red]Config error:[/] {e}")
        sys.exit(1)


def _make_adapter(config):
    """Instantiate the configured API adapter."""
    from src.api.google_flights import GoogleFlightsAdapter

    if config.api.provider == "google_flights":
        return GoogleFlightsAdapter()
    else:
        console.print(f"[red]Unknown API provider:[/] {config.api.provider}")
        sys.exit(1)


def _make_db(db_path: str):
    from src.db import Database

    return Database(db_path=db_path)


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option(
    "--config",
    "config_path",
    default="config.yaml",
    show_default=True,
    help="Path to config.yaml",
)
@click.option(
    "--db",
    "db_path",
    default="data/flights.db",
    show_default=True,
    help="Path to SQLite database",
)
@click.pass_context
def cli(ctx: click.Context, config_path: str, db_path: str) -> None:
    """FlightTracker — monitor and compare flight prices across date combinations."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["db_path"] = db_path


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Show per-fetch timing, browser events, and session telemetry.")
@click.pass_context
def search(ctx: click.Context, verbose: bool) -> None:
    """Run a full price search and store results."""
    from src.alerts import check_and_alert
    from src.search import run_search

    if verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(message)s",
            handlers=[RichHandler(console=console, show_path=False, markup=True)],
        )

    config = _load_config(ctx.obj["config_path"])
    adapter = _make_adapter(config)
    db = _make_db(ctx.obj["db_path"])

    try:
        results = run_search(config, adapter, db, verbose=verbose)
    finally:
        adapter.close()

    deals = check_and_alert(results, config.alerts)
    if deals:
        console.print(
            f"[bold green]{len(deals)} deal(s)[/] found below "
            f"${config.alerts.threshold_usd:.0f}/person!"
        )
        if config.alerts.email:
            console.print("[dim]Alert email sent.[/]")

    db.close()


# ---------------------------------------------------------------------------
# matrix
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--origin", "-o", default=None, help="Filter by origin airport code (e.g. DFW)")
@click.option("--destination", "-d", default=None, help="Filter by destination airport code (e.g. AMD)")
@click.pass_context
def matrix(ctx: click.Context, origin: str | None, destination: str | None) -> None:
    """Show a color-coded price matrix for depart/return date combinations."""
    from src.display import show_matrix

    config = _load_config(ctx.obj["config_path"])
    db = _make_db(ctx.obj["db_path"])

    routes = db.get_known_routes()
    if not routes:
        console.print("[yellow]No data yet. Run [bold]python main.py search[/] first.[/]")
        db.close()
        return

    # Filter routes if flags provided
    if origin:
        routes = [(o, d) for o, d in routes if o.upper() == origin.upper()]
    if destination:
        routes = [(o, d) for o, d in routes if d.upper() == destination.upper()]

    if not routes:
        console.print("[yellow]No matching routes in database.[/]")
        db.close()
        return

    depart_dates = [d.isoformat() for d in config.search.depart_dates.dates()]
    return_dates = [d.isoformat() for d in config.search.return_dates.dates()]

    for orig, dest in routes:
        matrix_data = db.get_matrix_snapshot(orig, dest)
        show_matrix(orig, dest, matrix_data, depart_dates, return_dates)

    db.close()


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--origin", "-o", default=None, help="Origin airport code (e.g. DFW)")
@click.option("--destination", "-d", default=None, help="Destination airport code (e.g. AMD)")
@click.option("--depart", default=None, help="Departure date YYYY-MM-DD")
@click.option("--return-date", "return_date", default=None, help="Return date YYYY-MM-DD")
@click.pass_context
def history(
    ctx: click.Context,
    origin: str | None,
    destination: str | None,
    depart: str | None,
    return_date: str | None,
) -> None:
    """Show a price history chart for a specific route + date combo."""
    from src.display import show_history

    db = _make_db(ctx.obj["db_path"])
    routes = db.get_known_routes()

    if not routes:
        console.print("[yellow]No data yet. Run [bold]python main.py search[/] first.[/]")
        db.close()
        return

    # If all four values provided, show directly
    if origin and destination and depart and return_date:
        hist = db.get_price_history(origin.upper(), destination.upper(), depart, return_date)
        show_history(origin.upper(), destination.upper(), depart, return_date, hist)
        db.close()
        return

    # Interactive selection
    config = _load_config(ctx.obj["config_path"])
    depart_dates = [d.isoformat() for d in config.search.depart_dates.dates()]
    return_dates = [d.isoformat() for d in config.search.return_dates.dates()]

    console.print("[bold]Available routes:[/]")
    for i, (o, d) in enumerate(routes, 1):
        console.print(f"  {i}. {o}→{d}")

    route_idx = click.prompt(
        "Select route number", type=click.IntRange(1, len(routes)), default=1
    )
    selected_origin, selected_dest = routes[route_idx - 1]

    console.print("\n[bold]Departure dates:[/]")
    for i, dd in enumerate(depart_dates, 1):
        console.print(f"  {i}. {dd}")
    dep_idx = click.prompt(
        "Select departure date", type=click.IntRange(1, len(depart_dates)), default=1
    )
    selected_depart = depart_dates[dep_idx - 1]

    console.print("\n[bold]Return dates:[/]")
    for i, rd in enumerate(return_dates, 1):
        console.print(f"  {i}. {rd}")
    ret_idx = click.prompt(
        "Select return date", type=click.IntRange(1, len(return_dates)), default=1
    )
    selected_return = return_dates[ret_idx - 1]

    hist = db.get_price_history(selected_origin, selected_dest, selected_depart, selected_return)
    show_history(selected_origin, selected_dest, selected_depart, selected_return, hist)
    db.close()


# ---------------------------------------------------------------------------
# watch
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--interval",
    default="6h",
    show_default=True,
    help="Search interval: e.g. 30m, 2h, 1d",
)
@click.pass_context
def watch(ctx: click.Context, interval: str) -> None:
    """Run searches on a schedule until stopped (Ctrl+C)."""
    from src.scheduler import start_watch, parse_interval

    try:
        parse_interval(interval)  # validate before loading everything
    except ValueError as e:
        console.print(f"[red]Error:[/] {e}")
        sys.exit(1)

    config = _load_config(ctx.obj["config_path"])
    adapter = _make_adapter(config)
    db = _make_db(ctx.obj["db_path"])

    start_watch(config, adapter, db, interval=interval)
    db.close()


# ---------------------------------------------------------------------------
# config show
# ---------------------------------------------------------------------------


@cli.command("config")
@click.option("--show", is_flag=True, default=False, help="Print the loaded config")
@click.pass_context
def config_cmd(ctx: click.Context, show: bool) -> None:
    """Show the loaded configuration (API keys are redacted)."""
    config = _load_config(ctx.obj["config_path"])

    if not show:
        console.print("Use [bold]--show[/] to print the loaded config.")
        return

    table = Table(title="Loaded Configuration", box=box.ROUNDED, show_header=False)
    table.add_column("Key", style="bold cyan")
    table.add_column("Value")

    table.add_row("API provider", config.api.provider)
    table.add_row("Origins", ", ".join(config.search.origins))
    table.add_row("Destinations", ", ".join(config.search.destinations))
    table.add_row("Depart dates", f"{config.search.depart_dates.start} → {config.search.depart_dates.end}")
    table.add_row("Return dates", f"{config.search.return_dates.start} → {config.search.return_dates.end}")
    table.add_row("Passengers", str(config.search.passengers))
    table.add_row("Cabin class", config.search.cabin_class)
    table.add_row("Rate limit delay", f"{config.search.rate_limit_delay}s")
    table.add_row("Max results/search", str(config.search.max_results_per_search))
    table.add_row("Alerts enabled", str(config.alerts.enabled))
    if config.alerts.enabled:
        table.add_row("Alert threshold", f"${config.alerts.threshold_usd:.0f}/person")
        if config.alerts.email:
            table.add_row("Alert recipients", ", ".join(config.alerts.email.recipients))

    console.print(table)

    depart_count = len(config.search.depart_dates.dates())
    return_count = len(config.search.return_dates.dates())
    total_combos = (
        len(config.search.origins)
        * len(config.search.destinations)
        * depart_count
        * return_count
    )
    console.print(
        f"\n[dim]Total combinations per run: "
        f"{len(config.search.origins)} origins × "
        f"{len(config.search.destinations)} destinations × "
        f"{depart_count} depart × {return_count} return = "
        f"[bold]{total_combos}[/] API calls[/]"
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    cli()
