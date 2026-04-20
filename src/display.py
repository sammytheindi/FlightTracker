"""Terminal display: date matrix (Rich) and price history chart (plotext)."""

from __future__ import annotations

from typing import Optional

import plotext as plt
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

# Price thresholds for color coding (per person, USD)
_GREEN_THRESHOLD = 900
_YELLOW_THRESHOLD = 1200


def show_matrix(
    origin: str,
    destination: str,
    matrix: dict[tuple[str, str], float],
    depart_dates: list[str],
    return_dates: list[str],
) -> None:
    """
    Render a color-coded price matrix to the terminal.

    Rows = departure dates, Columns = return dates.
    Colors: green (cheap), yellow (mid), red (expensive), dim (no data).

    Args:
        origin: Origin airport code.
        destination: Destination airport code.
        matrix: Dict of (depart_date, return_date) → price_per_person.
        depart_dates: Sorted list of departure date strings (rows).
        return_dates: Sorted list of return date strings (columns).
    """
    if not matrix:
        console.print(
            f"[yellow]No data for {origin}→{destination}. Run [bold]python main.py search[/] first.[/]"
        )
        return

    table = Table(
        title=f"[bold]{origin} → {destination}[/]  (price per person, USD)",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
        border_style="dim",
    )

    # Header row: return dates (shortened to MM-DD)
    table.add_column("Depart ↓ / Return →", style="bold", justify="center")
    for rd in return_dates:
        table.add_column(_short_date(rd), justify="center", min_width=8)

    # Data rows
    for dd in depart_dates:
        row_cells: list[str] = [f"[bold]{_short_date(dd)}[/]"]
        for rd in return_dates:
            price = matrix.get((dd, rd))
            if price is None:
                row_cells.append("[dim]—[/]")
            else:
                row_cells.append(_colored_price(price))
        table.add_row(*row_cells)

    # Legend
    console.print(table)
    console.print(
        f"  [green]■[/] < ${_GREEN_THRESHOLD}   "
        f"[yellow]■[/] ${_GREEN_THRESHOLD}–${_YELLOW_THRESHOLD}   "
        f"[red]■[/] > ${_YELLOW_THRESHOLD}   "
        f"[dim]—[/] no data\n"
    )


def show_history(
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    history: list[tuple[str, float]],
) -> None:
    """
    Render an in-terminal price history chart using plotext.

    Args:
        origin: Origin airport code.
        destination: Destination airport code.
        depart_date: Departure date for this combo.
        return_date: Return date for this combo.
        history: List of (fetched_at_iso, price_per_person), oldest first.
    """
    if not history:
        console.print(
            f"[yellow]No price history for {origin}→{destination} "
            f"dep {depart_date} / ret {return_date}.[/]"
        )
        return

    timestamps = [entry[0] for entry in history]
    prices = [entry[1] for entry in history]

    # Use short labels for x-axis: date part only
    x_labels = [ts[:10] for ts in timestamps]

    plt.clear_figure()
    plt.theme("dark")
    plt.plot_size(width=80, height=20)

    # Use indices for x so plotext renders evenly spaced
    x_indices = list(range(len(prices)))
    plt.plot(x_indices, prices, color="green", marker="braille")
    plt.scatter(x_indices, prices, color="green", marker="dot")

    plt.title(f"{origin} → {destination}  |  dep {depart_date}  /  ret {return_date}")
    plt.xlabel("Check date")
    plt.ylabel("Price / person (USD)")

    # Set x-axis ticks to dates
    if len(x_labels) <= 10:
        plt.xticks(x_indices, x_labels)
    else:
        # Show every Nth label to avoid crowding
        step = max(1, len(x_labels) // 8)
        chosen = x_indices[::step]
        plt.xticks(chosen, [x_labels[i] for i in chosen])

    if len(prices) > 1:
        min_price = min(prices)
        max_price = max(prices)
        # Draw horizontal reference lines
        plt.hline(min_price, color="cyan")

    plt.show()

    if prices:
        console.print(
            f"  Min: [green]${min(prices):.0f}[/]   "
            f"Max: [red]${max(prices):.0f}[/]   "
            f"Latest: [bold]${prices[-1]:.0f}[/]"
        )


def show_cheapest_routes(
    routes: list[tuple[str, str]],
    db_query_fn,  # callable(origin, dest) -> list of rows
) -> None:
    """
    Print a summary table of the cheapest offer ever seen per route.

    Args:
        routes: List of (origin, destination) pairs.
        db_query_fn: Function to fetch cheapest results from DB.
    """
    if not routes:
        console.print("[yellow]No routes in database yet.[/]")
        return

    table = Table(
        title="All-Time Cheapest Offers",
        box=box.SIMPLE_HEAVY,
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Route", style="bold")
    table.add_column("Depart", justify="center")
    table.add_column("Return", justify="center")
    table.add_column("$/person", justify="right")
    table.add_column("Airline", justify="center")
    table.add_column("Stops", justify="center")
    table.add_column("Duration", justify="center")

    for origin, destination in routes:
        rows = db_query_fn(origin, destination, limit=1)
        if rows:
            r = rows[0]
            table.add_row(
                f"{origin}→{destination}",
                r["depart_date"],
                r["return_date"],
                _colored_price(r["price_per_person"]),
                r["airline"],
                str(r["stops"]),
                f"{r['duration_hrs']:.1f}h",
            )

    console.print(table)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _short_date(iso_date: str) -> str:
    """Convert YYYY-MM-DD to MM-DD."""
    parts = iso_date.split("-")
    if len(parts) == 3:
        return f"{parts[1]}-{parts[2]}"
    return iso_date


def _colored_price(price: float) -> str:
    """Return a Rich-markup price string colored by threshold."""
    formatted = f"${price:.0f}"
    if price < _GREEN_THRESHOLD:
        return f"[bold green]{formatted}[/]"
    elif price < _YELLOW_THRESHOLD:
        return f"[yellow]{formatted}[/]"
    else:
        return f"[red]{formatted}[/]"
