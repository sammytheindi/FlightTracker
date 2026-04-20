"""Smoke tests for src/display.py — verify no crashes, basic output checks."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from src.display import (
    _colored_price,
    _short_date,
    show_history,
    show_matrix,
)
from tests.fixtures.sample_results import MULTI_DATE_RESULTS


# ---------------------------------------------------------------------------
# Helper: capture rich output
# ---------------------------------------------------------------------------


def capture_rich(fn, *args, **kwargs) -> str:
    """Run fn with a Rich Console writing to a StringIO; return output."""
    buf = StringIO()
    test_console = Console(file=buf, force_terminal=False, width=120)
    with patch("src.display.console", test_console):
        fn(*args, **kwargs)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# _short_date
# ---------------------------------------------------------------------------


def test_short_date():
    assert _short_date("2026-12-15") == "12-15"


def test_short_date_passthrough_on_bad_format():
    assert _short_date("bad") == "bad"


# ---------------------------------------------------------------------------
# _colored_price
# ---------------------------------------------------------------------------


def test_colored_price_cheap():
    result = _colored_price(700.0)
    assert "$700" in result
    assert "green" in result


def test_colored_price_mid():
    result = _colored_price(1050.0)
    assert "$1050" in result
    assert "yellow" in result


def test_colored_price_expensive():
    result = _colored_price(1400.0)
    assert "$1400" in result
    assert "red" in result


# ---------------------------------------------------------------------------
# show_matrix
# ---------------------------------------------------------------------------


def test_show_matrix_no_data_prints_warning():
    output = capture_rich(
        show_matrix,
        origin="DFW",
        destination="AMD",
        matrix={},
        depart_dates=["2026-12-10"],
        return_dates=["2027-01-01"],
    )
    assert "No data" in output or "search" in output.lower()


def test_show_matrix_renders_prices():
    matrix = {("2026-12-10", "2027-01-01"): 850.0, ("2026-12-15", "2027-01-05"): 1100.0}
    depart_dates = ["2026-12-10", "2026-12-15"]
    return_dates = ["2027-01-01", "2027-01-05"]

    output = capture_rich(
        show_matrix,
        origin="DFW",
        destination="AMD",
        matrix=matrix,
        depart_dates=depart_dates,
        return_dates=return_dates,
    )
    assert "850" in output
    assert "1100" in output


def test_show_matrix_missing_cell_shows_dash():
    # Only one combo has data
    matrix = {("2026-12-10", "2027-01-01"): 850.0}
    depart_dates = ["2026-12-10"]
    return_dates = ["2027-01-01", "2027-01-05"]

    output = capture_rich(
        show_matrix,
        origin="DFW",
        destination="AMD",
        matrix=matrix,
        depart_dates=depart_dates,
        return_dates=return_dates,
    )
    assert "—" in output  # em-dash for missing cell


# ---------------------------------------------------------------------------
# show_history
# ---------------------------------------------------------------------------


def test_show_history_no_data_prints_warning():
    output = capture_rich(
        show_history,
        origin="DFW",
        destination="AMD",
        depart_date="2026-12-15",
        return_date="2027-01-05",
        history=[],
    )
    assert "No price history" in output


def test_show_history_renders_without_crash():
    history = [
        ("2026-04-10T10:00:00", 950.0),
        ("2026-04-11T10:00:00", 920.0),
        ("2026-04-12T10:00:00", 890.0),
    ]
    # plotext writes to stdout; patch it out to avoid terminal side effects
    with patch("plotext.show"):
        output = capture_rich(
            show_history,
            origin="DFW",
            destination="AMD",
            depart_date="2026-12-15",
            return_date="2027-01-05",
            history=history,
        )
    # Should at least print the min/max summary line
    assert "890" in output or "950" in output
