"""Tests for src/search.py — uses a fake adapter, no real API calls."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

from src.api.base import FlightResult, FlightSearchAdapter
from src.config import load_config
from src.db import Database
from src.search import run_search
from tests.fixtures.sample_results import make_result


# ---------------------------------------------------------------------------
# Fake adapter
# ---------------------------------------------------------------------------


class FakeAdapter(FlightSearchAdapter):
    """Returns deterministic results; records all calls made to it."""

    def __init__(self, results_per_call: list[FlightResult] | None = None) -> None:
        self.calls: list[dict] = []
        self._results = results_per_call or []

    def search(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str,
        passengers: int,
        cabin_class: str = "ECONOMY",
        max_results: int = 5,
    ) -> list[FlightResult]:
        self.calls.append(
            dict(
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                return_date=return_date,
                passengers=passengers,
            )
        )
        # Return copies with the correct route/date context
        return [
            make_result(
                origin=origin,
                destination=destination,
                depart_date=depart_date,
                return_date=return_date,
                price_per_person=r.price_per_person,
            )
            for r in self._results
        ]


# ---------------------------------------------------------------------------
# Config fixture
# ---------------------------------------------------------------------------


MINIMAL_CONFIG = {
    "api": {
        "provider": "google_flights",
    },
    "search": {
        "origins": ["DFW"],
        "destinations": ["AMD"],
        "depart_dates": {"start": "2026-12-10", "end": "2026-12-11"},
        "return_dates": {"start": "2027-01-01", "end": "2027-01-02"},
        "passengers": 2,
        "cabin_class": "ECONOMY",
        "rate_limit_delay": 0,  # no sleep in tests
        "max_results_per_search": 5,
    },
    "alerts": {"enabled": False, "threshold_usd": 1000},
}


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(MINIMAL_CONFIG))
    return load_config(path)


@pytest.fixture
def db():
    database = Database(db_path=":memory:")
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_search_calls_all_combinations(config, db):
    """Adapter should be called once per (origin, destination, depart, return) combo."""
    adapter = FakeAdapter()
    run_search(config, adapter, db)

    # 1 origin × 1 destination × 2 depart dates × 2 return dates = 4 calls
    assert len(adapter.calls) == 4


def test_search_results_stored_in_db(config, db):
    adapter = FakeAdapter(results_per_call=[make_result(price_per_person=900.0)])
    run_search(config, adapter, db)

    routes = db.get_known_routes()
    assert ("DFW", "AMD") in routes

    matrix = db.get_matrix_snapshot("DFW", "AMD")
    assert len(matrix) == 4  # 2 depart × 2 return


def test_search_no_results_does_not_crash(config, db):
    adapter = FakeAdapter(results_per_call=[])  # empty results
    results = run_search(config, adapter, db)

    assert results == []
    assert db.get_known_routes() == []


def test_search_correct_passengers_passed(config, db):
    adapter = FakeAdapter()
    run_search(config, adapter, db)

    for call in adapter.calls:
        assert call["passengers"] == 2


def test_search_multiple_origins(config, db):
    import dataclasses

    two_origin_config = dataclasses.replace(
        config,
        search=dataclasses.replace(config.search, origins=["DFW", "DAL"]),
    )

    adapter = FakeAdapter(results_per_call=[make_result()])
    run_search(two_origin_config, adapter, db)

    # 2 origins × 1 dest × 2 depart × 2 return = 8 calls
    assert len(adapter.calls) == 8
    origins_called = {c["origin"] for c in adapter.calls}
    assert origins_called == {"DFW", "DAL"}


def test_search_rate_limit_delay_respected(config, db):
    """Ensure rate_limit_delay is honored — here we set 0 to skip sleeping."""
    import time

    adapter = FakeAdapter()
    start = time.monotonic()
    run_search(config, adapter, db)
    elapsed = time.monotonic() - start

    # With delay=0 it should complete near-instantly (< 1s)
    assert elapsed < 1.0
