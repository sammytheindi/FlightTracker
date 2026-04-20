"""Tests for src/db.py — using in-memory SQLite."""

import pytest

from src.db import Database
from tests.fixtures.sample_results import (
    CHEAP_RESULT,
    EXPENSIVE_RESULT,
    MID_RESULT,
    MULTI_DATE_RESULTS,
    make_result,
)


@pytest.fixture
def db():
    """Fresh in-memory database for each test."""
    database = Database(db_path=":memory:")
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Insert + basic reads
# ---------------------------------------------------------------------------


def test_insert_single_result(db):
    db.insert_result(CHEAP_RESULT)
    routes = db.get_known_routes()
    assert ("DFW", "AMD") in routes


def test_insert_results_bulk(db):
    db.insert_results(MULTI_DATE_RESULTS)
    routes = db.get_known_routes()
    assert ("DFW", "AMD") in routes


def test_get_known_routes_empty(db):
    assert db.get_known_routes() == []


def test_get_known_routes_multiple(db):
    db.insert_result(make_result(origin="DFW", destination="AMD"))
    db.insert_result(make_result(origin="DAL", destination="AMD"))
    routes = db.get_known_routes()
    assert ("DAL", "AMD") in routes
    assert ("DFW", "AMD") in routes


# ---------------------------------------------------------------------------
# Matrix snapshot
# ---------------------------------------------------------------------------


def test_get_matrix_snapshot_returns_cheapest(db):
    # Insert two results for same combo with different prices
    r1 = make_result(price_per_person=900.0, fetched_at="2026-04-19T10:00:00")
    r2 = make_result(price_per_person=750.0, fetched_at="2026-04-19T11:00:00")
    db.insert_results([r1, r2])

    matrix = db.get_matrix_snapshot("DFW", "AMD")
    assert ("2026-12-15", "2027-01-05") in matrix
    assert matrix[("2026-12-15", "2027-01-05")] == pytest.approx(750.0)


def test_get_matrix_snapshot_multiple_combos(db):
    db.insert_results(MULTI_DATE_RESULTS)
    matrix = db.get_matrix_snapshot("DFW", "AMD")

    assert len(matrix) == len(MULTI_DATE_RESULTS)
    assert ("2026-12-10", "2027-01-01") in matrix
    assert ("2026-12-20", "2027-01-10") in matrix


def test_get_matrix_snapshot_empty(db):
    matrix = db.get_matrix_snapshot("DFW", "AMD")
    assert matrix == {}


def test_get_matrix_snapshot_route_isolation(db):
    db.insert_result(make_result(origin="DFW", destination="AMD"))
    db.insert_result(make_result(origin="DAL", destination="AMD"))

    matrix_dfw = db.get_matrix_snapshot("DFW", "AMD")
    matrix_dal = db.get_matrix_snapshot("DAL", "AMD")

    assert len(matrix_dfw) == 1
    assert len(matrix_dal) == 1


# ---------------------------------------------------------------------------
# Price history
# ---------------------------------------------------------------------------


def test_get_price_history_single_entry(db):
    db.insert_result(CHEAP_RESULT)
    hist = db.get_price_history("DFW", "AMD", "2026-12-15", "2027-01-05")

    assert len(hist) == 1
    assert hist[0][1] == pytest.approx(800.0)


def test_get_price_history_multiple_fetches(db):
    r1 = make_result(price_per_person=900.0, fetched_at="2026-04-19T10:00:00")
    r2 = make_result(price_per_person=850.0, fetched_at="2026-04-19T11:00:00")
    r3 = make_result(price_per_person=820.0, fetched_at="2026-04-20T10:00:00")
    db.insert_results([r1, r2, r3])

    hist = db.get_price_history("DFW", "AMD", "2026-12-15", "2027-01-05")

    # Groups by fetch_date (calendar day): Apr 19 and Apr 20 → 2 groups
    assert len(hist) == 2
    # Keys are YYYY-MM-DD date strings, sorted oldest first
    assert hist[0][0] == "2026-04-19"
    assert hist[1][0] == "2026-04-20"
    # Apr 19 group takes MIN of 900 and 850
    assert hist[0][1] == pytest.approx(850.0)
    assert hist[1][1] == pytest.approx(820.0)


def test_get_price_history_empty(db):
    hist = db.get_price_history("DFW", "AMD", "2026-12-15", "2027-01-05")
    assert hist == []


def test_get_price_history_combo_isolation(db):
    r_a = make_result(depart_date="2026-12-10", return_date="2027-01-01", price_per_person=900.0)
    r_b = make_result(depart_date="2026-12-15", return_date="2027-01-05", price_per_person=700.0)
    db.insert_results([r_a, r_b])

    hist = db.get_price_history("DFW", "AMD", "2026-12-15", "2027-01-05")
    assert len(hist) == 1
    assert hist[0][1] == pytest.approx(700.0)


# ---------------------------------------------------------------------------
# Cheapest results
# ---------------------------------------------------------------------------


def test_get_cheapest_results(db):
    db.insert_results([CHEAP_RESULT, MID_RESULT, EXPENSIVE_RESULT])
    rows = db.get_cheapest_results("DFW", "AMD", limit=2)

    assert len(rows) == 2
    assert rows[0]["price_per_person"] == pytest.approx(800.0)
    assert rows[1]["price_per_person"] == pytest.approx(1050.0)


# ---------------------------------------------------------------------------
# Deduplication
# ---------------------------------------------------------------------------


def test_exact_same_day_duplicate_is_dropped(db):
    """Inserting the exact same offer twice on the same day stores only one row."""
    r = make_result(price_per_person=900.0, fetched_at="2026-04-19T10:00:00")
    r_again = make_result(price_per_person=900.0, fetched_at="2026-04-19T14:00:00")
    db.insert_results([r, r_again])

    rows = db.get_cheapest_results("DFW", "AMD")
    assert len(rows) == 1


def test_same_offer_different_price_same_day_is_kept(db):
    """Intra-day price change is recorded as a separate row."""
    r1 = make_result(price_per_person=900.0, fetched_at="2026-04-19T10:00:00")
    r2 = make_result(price_per_person=850.0, fetched_at="2026-04-19T14:00:00")
    db.insert_results([r1, r2])

    rows = db.get_cheapest_results("DFW", "AMD")
    assert len(rows) == 2


def test_same_offer_different_day_is_kept(db):
    """Same price on a different calendar day is a new observation."""
    r1 = make_result(price_per_person=900.0, fetched_at="2026-04-19T10:00:00")
    r2 = make_result(price_per_person=900.0, fetched_at="2026-04-20T10:00:00")
    db.insert_results([r1, r2])

    rows = db.get_cheapest_results("DFW", "AMD")
    assert len(rows) == 2


def test_get_price_history_returns_date_strings(db):
    """get_price_history keys are YYYY-MM-DD strings, not full ISO timestamps."""
    r = make_result(price_per_person=900.0, fetched_at="2026-04-19T10:00:00")
    db.insert_result(r)

    hist = db.get_price_history("DFW", "AMD", "2026-12-15", "2027-01-05")
    assert hist[0][0] == "2026-04-19"
