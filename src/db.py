"""SQLite price history storage."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from src.api.base import FlightResult


DEFAULT_DB_PATH = Path("data/flights.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS price_history (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    origin           TEXT    NOT NULL,
    destination      TEXT    NOT NULL,
    depart_date      TEXT    NOT NULL,
    return_date      TEXT    NOT NULL,
    price_usd        REAL    NOT NULL,
    price_per_person REAL    NOT NULL,
    airline          TEXT    NOT NULL,
    stops            INTEGER NOT NULL,
    duration_hrs     REAL    NOT NULL,
    fetched_at       TEXT    NOT NULL,
    fetch_date       TEXT    NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_route_dates
    ON price_history (origin, destination, depart_date, return_date);

CREATE INDEX IF NOT EXISTS idx_fetched_at
    ON price_history (fetched_at);

"""


class Database:
    """Thin wrapper around a SQLite connection for price history operations."""

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._apply_schema()
        self._migrate()

    def _apply_schema(self) -> None:
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def _migrate(self) -> None:
        """Idempotent: adds fetch_date column if missing, backfills it, then creates unique index."""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(price_history)").fetchall()}
        if "fetch_date" not in cols:
            self._conn.execute("ALTER TABLE price_history ADD COLUMN fetch_date TEXT NOT NULL DEFAULT ''")
            self._conn.execute("UPDATE price_history SET fetch_date = date(fetched_at) WHERE fetch_date = ''")
            self._conn.commit()
        self._conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_offer_per_day
                ON price_history (origin, destination, depart_date, return_date,
                                  airline, stops, price_per_person, fetch_date)
            """
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert_result(self, result: FlightResult) -> None:
        """Persist a single flight result, ignoring exact same-day duplicates."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO price_history
                (origin, destination, depart_date, return_date,
                 price_usd, price_per_person, airline, stops, duration_hrs,
                 fetched_at, fetch_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, date(?))
            """,
            (
                result.origin,
                result.destination,
                result.depart_date,
                result.return_date,
                result.price_usd,
                result.price_per_person,
                result.airline,
                result.stops,
                result.duration_hrs,
                result.fetched_at,
                result.fetched_at,
            ),
        )
        self._conn.commit()

    def insert_results(self, results: list[FlightResult]) -> None:
        """Bulk insert, silently dropping same-day exact duplicates."""
        self._conn.executemany(
            """
            INSERT OR IGNORE INTO price_history
                (origin, destination, depart_date, return_date,
                 price_usd, price_per_person, airline, stops, duration_hrs,
                 fetched_at, fetch_date)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, date(?))
            """,
            [
                (
                    r.origin,
                    r.destination,
                    r.depart_date,
                    r.return_date,
                    r.price_usd,
                    r.price_per_person,
                    r.airline,
                    r.stops,
                    r.duration_hrs,
                    r.fetched_at,
                    r.fetched_at,
                )
                for r in results
            ],
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_matrix_snapshot(
        self, origin: str, destination: str
    ) -> dict[tuple[str, str], float]:
        """
        Return the best (lowest) price per person seen for each
        (depart_date, return_date) combo.

        Returns:
            Dict keyed by (depart_date, return_date) → lowest price_per_person.
        """
        rows = self._conn.execute(
            """
            SELECT depart_date, return_date, MIN(price_per_person) AS best_price
            FROM price_history
            WHERE origin = ? AND destination = ?
            GROUP BY depart_date, return_date
            """,
            (origin, destination),
        ).fetchall()

        return {(row["depart_date"], row["return_date"]): row["best_price"] for row in rows}

    def get_price_history(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str,
    ) -> list[tuple[str, float]]:
        """
        Return the time series of cheapest prices seen for one specific combo.

        Returns:
            List of (fetched_at_iso, price_per_person), sorted oldest-first.
        """
        rows = self._conn.execute(
            """
            SELECT fetch_date, MIN(price_per_person) AS best_price
            FROM price_history
            WHERE origin = ? AND destination = ?
              AND depart_date = ? AND return_date = ?
            GROUP BY fetch_date
            ORDER BY fetch_date ASC
            """,
            (origin, destination, depart_date, return_date),
        ).fetchall()

        return [(row["fetch_date"], row["best_price"]) for row in rows]

    def get_price_trend(
        self, origin: str, destination: str, days: int
    ) -> list[dict]:
        """
        Return daily aggregate price stats for a route over the last N days.

        Each row contains fetch_date, avg_price, min_price, max_price aggregated
        across all depart×return combinations scraped on that day.

        Returns:
            List of dicts with keys: fetch_date, avg_price, min_price, max_price.
        """
        rows = self._conn.execute(
            """
            SELECT fetch_date,
                   AVG(price_per_person) AS avg_price,
                   MIN(price_per_person) AS min_price,
                   MAX(price_per_person) AS max_price
            FROM price_history
            WHERE origin = ? AND destination = ?
              AND fetch_date >= date('now', '-' || ? || ' days')
            GROUP BY fetch_date
            ORDER BY fetch_date ASC
            """,
            (origin, destination, days),
        ).fetchall()

        return [
            {
                "fetch_date": row["fetch_date"],
                "avg_price": row["avg_price"],
                "min_price": row["min_price"],
                "max_price": row["max_price"],
            }
            for row in rows
        ]

    def get_matrix_latest(
        self, origin: str, destination: str
    ) -> dict[tuple[str, str], float]:
        """
        Return best price per (depart_date, return_date) from the most recent scrape day.

        Returns:
            Dict keyed by (depart_date, return_date) → lowest price_per_person.
        """
        rows = self._conn.execute(
            """
            SELECT depart_date, return_date, MIN(price_per_person) AS best_price
            FROM price_history
            WHERE origin = ? AND destination = ?
              AND fetch_date = (
                  SELECT MAX(fetch_date) FROM price_history
                  WHERE origin = ? AND destination = ?
              )
            GROUP BY depart_date, return_date
            """,
            (origin, destination, origin, destination),
        ).fetchall()

        return {(row["depart_date"], row["return_date"]): row["best_price"] for row in rows}

    def get_known_routes(self) -> list[tuple[str, str]]:
        """Return all distinct (origin, destination) pairs in the database."""
        rows = self._conn.execute(
            "SELECT DISTINCT origin, destination FROM price_history ORDER BY origin, destination"
        ).fetchall()
        return [(row["origin"], row["destination"]) for row in rows]

    def get_cheapest_results(
        self, origin: str, destination: str, limit: int = 10
    ) -> list[sqlite3.Row]:
        """Return the cheapest individual results ever seen for a route."""
        return self._conn.execute(
            """
            SELECT * FROM price_history
            WHERE origin = ? AND destination = ?
            ORDER BY price_per_person ASC
            LIMIT ?
            """,
            (origin, destination, limit),
        ).fetchall()

    def close(self) -> None:
        self._conn.close()
