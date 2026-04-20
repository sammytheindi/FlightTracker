"""Shared FlightResult fixtures for tests."""

from src.api.base import FlightResult


def make_result(
    origin: str = "DFW",
    destination: str = "AMD",
    depart_date: str = "2026-12-15",
    return_date: str = "2027-01-05",
    price_per_person: float = 950.0,
    passengers: int = 2,
    airline: str = "EK",
    stops: int = 1,
    duration_hrs: float = 18.5,
    fetched_at: str = "2026-04-19T10:00:00",
) -> FlightResult:
    return FlightResult(
        origin=origin,
        destination=destination,
        depart_date=depart_date,
        return_date=return_date,
        price_usd=round(price_per_person * passengers, 2),
        price_per_person=price_per_person,
        airline=airline,
        stops=stops,
        duration_hrs=duration_hrs,
        fetched_at=fetched_at,
    )


CHEAP_RESULT = make_result(price_per_person=800.0, fetched_at="2026-04-19T10:00:00")
MID_RESULT = make_result(price_per_person=1050.0, fetched_at="2026-04-19T11:00:00")
EXPENSIVE_RESULT = make_result(price_per_person=1400.0, fetched_at="2026-04-19T12:00:00")

MULTI_DATE_RESULTS = [
    make_result(depart_date="2026-12-10", return_date="2027-01-01", price_per_person=850.0),
    make_result(depart_date="2026-12-10", return_date="2027-01-05", price_per_person=920.0),
    make_result(depart_date="2026-12-15", return_date="2027-01-01", price_per_person=780.0),
    make_result(depart_date="2026-12-15", return_date="2027-01-05", price_per_person=1100.0),
    make_result(depart_date="2026-12-20", return_date="2027-01-10", price_per_person=1350.0),
]
