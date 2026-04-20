"""Google Flights adapter using the fast-flights library.

fast-flights handles building the protobuf query and making the HTTP request.
We parse flight data from the aria-label attribute on each flight card, which
is part of Google's accessibility contract and far more stable than CSS class
names (which change whenever a frontend engineer does a refactor).

Aria-label format (as of April 2026):
  "From 5439 US dollars round trip total. 2 stops flight with Air France and
   IndiGo. Leaves Dallas Fort Worth International Airport at 4:05 PM on
   Sunday, December 20 and arrives at ... Total duration 26 hr 30 min. ..."

No API key or account required — completely free.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from selectolax.lexbor import LexborHTMLParser, LexborNode
from fast_flights import FlightData, Passengers
from fast_flights.filter import TFSData
from src.api.playwright_fetch import BrowserSession

from src.api.base import FlightResult, FlightSearchAdapter

logger = logging.getLogger(__name__)

_SEAT_MAP: dict[str, str] = {
    "ECONOMY": "economy",
    "PREMIUM_ECONOMY": "premium-economy",
    "BUSINESS": "business",
    "FIRST": "first",
}

# Regex patterns against the aria-label string.
# These are semantically meaningful accessibility strings that Google must
# keep stable — unlike CSS class names which are implementation details.
_RE_PRICE    = re.compile(r"From ([\d,]+) US dollars", re.IGNORECASE)
_RE_STOPS    = re.compile(r"(\d+) stops? flight|Nonstop flight", re.IGNORECASE)
_RE_AIRLINES = re.compile(r"(?:\d+ stops? flight|Nonstop flight) with (.+?)\. Leaves", re.IGNORECASE)
_RE_DURATION = re.compile(r"Total duration (.+?)\.", re.IGNORECASE)


class GoogleFlightsAdapter(FlightSearchAdapter):
    """
    Flight search via Google Flights (no API key required).

    Opens a single Playwright browser session for the lifetime of the adapter
    and reuses it across all search() calls — one browser launch per run,
    not one per request.
    """

    def __init__(self) -> None:
        self._session = BrowserSession()
        self._session.open()

    def close(self) -> None:
        """Close the browser. Call when done with all searches."""
        self._session.close()

    def __enter__(self) -> "GoogleFlightsAdapter":
        return self

    def __exit__(self, *_) -> None:
        self.close()

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
        seat = _SEAT_MAP.get(cabin_class, "economy")

        try:
            tfs = TFSData.from_interface(
                flight_data=[
                    FlightData(date=depart_date, from_airport=origin, to_airport=destination),
                    FlightData(date=return_date, from_airport=destination, to_airport=origin),
                ],
                trip="round-trip",
                passengers=Passengers(adults=passengers),
                seat=seat,
            )
            params = {
                "tfs": tfs.as_b64().decode("utf-8"),
                "hl": "en",
                "tfu": "EgQIABABIgA",
                "curr": "",
            }
            response = self._session.fetch(params)
        except Exception as e:
            logger.warning(
                "Google Flights request failed for %s→%s dep=%s ret=%s: %s",
                origin, destination, depart_date, return_date, e,
            )
            return []

        results = _parse_html(
            response.text, origin, destination, depart_date, return_date, passengers
        )
        results = results[:max_results]
        results.sort(key=lambda r: r.price_per_person)
        return results


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------


def _parse_html(
    html: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    passengers: int,
) -> list[FlightResult]:
    """Parse Google Flights HTML into FlightResult objects via aria-labels."""
    parser = LexborHTMLParser(html)
    results: list[FlightResult] = []

    for card in parser.css("div.JMc5Xc[aria-label]"):
        label = card.attributes.get("aria-label", "")
        if not label:
            continue
        result = _parse_aria_label(label, origin, destination, depart_date, return_date, passengers)
        if result is not None:
            results.append(result)

    if not results:
        logger.warning(
            "No flights parsed for %s→%s dep=%s ret=%s. "
            "Google may have changed the aria-label format — run: make check-selectors",
            origin, destination, depart_date, return_date,
        )

    return results


def _parse_aria_label(
    label: str,
    origin: str,
    destination: str,
    depart_date: str,
    return_date: str,
    passengers: int,
) -> Optional[FlightResult]:
    """
    Extract flight data from a Google Flights accessibility label string.

    Args:
        label: The aria-label attribute value from a flight card.

    Returns:
        FlightResult or None if the label doesn't contain expected fields.
    """
    try:
        price_match = _RE_PRICE.search(label)
        if not price_match:
            return None
        price_per_person = float(price_match.group(1).replace(",", ""))

        stops_match = _RE_STOPS.search(label)
        if stops_match:
            stops = 0 if stops_match.group(0).lower().startswith("nonstop") else int(stops_match.group(1))
        else:
            stops = -1  # unknown

        airlines_match = _RE_AIRLINES.search(label)
        airline = airlines_match.group(1).strip() if airlines_match else "Unknown"

        duration_match = _RE_DURATION.search(label)
        duration_hrs = _parse_duration(duration_match.group(1)) if duration_match else 0.0

        return FlightResult(
            origin=origin,
            destination=destination,
            depart_date=depart_date,
            return_date=return_date,
            price_usd=round(price_per_person * passengers, 2),
            price_per_person=round(price_per_person, 2),
            airline=airline,
            stops=stops,
            duration_hrs=round(duration_hrs, 2),
        )
    except Exception as e:
        logger.debug("Failed to parse aria-label: %s — %s", e, label[:120])
        return None


def _parse_duration(duration_str: str) -> float:
    """
    Parse a duration string to total hours.

    "26 hr 30 min" → 26.5
    "2 hr"         → 2.0
    "45 min"       → 0.75
    """
    hours, minutes = 0.0, 0.0
    hr_m = re.search(r"(\d+)\s*hr", duration_str, re.IGNORECASE)
    min_m = re.search(r"(\d+)\s*min", duration_str, re.IGNORECASE)
    if hr_m:
        hours = float(hr_m.group(1))
    if min_m:
        minutes = float(min_m.group(1))
    return hours + minutes / 60.0
