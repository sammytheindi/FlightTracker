"""Unit tests for the Google Flights aria-label parser.

These tests use real aria-label strings captured from Google Flights
(April 2026) to verify the regex patterns and end-to-end parsing.
No network calls are made.
"""

import pytest
from src.api.google_flights import (
    _RE_PRICE,
    _RE_STOPS,
    _RE_AIRLINES,
    _RE_DURATION,
    _parse_aria_label,
    _parse_duration,
)

# ---------------------------------------------------------------------------
# Real aria-label fixtures captured from Google Flights (April 2026)
# ---------------------------------------------------------------------------

LABEL_2_STOPS = (
    "From 5439 US dollars round trip total. 2 stops flight with Air France and IndiGo. "
    "Leaves Dallas Fort Worth International Airport at 4:05 PM on Sunday, December 20 "
    "and arrives at Sardar Vallabhbhai Patel International Airport at 6:05 AM on Tuesday, "
    "December 22. Total duration 26 hr 30 min. Layover (1 of 2) is a 2 hr 40 min layover "
    "at Paris Charles de Gaulle Airport in Paris. Carbon emissions estimate: 1,814 kilograms."
)

LABEL_1_STOP = (
    "From 6410 US dollars round trip total. 1 stop flight with Qatar Airways. "
    "Leaves Dallas Fort Worth International Airport at 5:30 PM on Sunday, December 20 "
    "and arrives at Sardar Vallabhbhai Patel International Airport at 2:10 AM on Tuesday, "
    "December 22. Total duration 21 hr 10 min. Layover (1 of 1) is a 3 hr 30 min layover "
    "at Hamad International Airport in Doha. Carbon emissions estimate: 1,900 kilograms."
)

LABEL_NONSTOP = (
    "From 899 US dollars round trip total. Nonstop flight with United. "
    "Leaves Dallas Fort Worth International Airport at 8:00 AM on Monday, December 15 "
    "and arrives at John F. Kennedy International Airport at 12:30 PM on Monday, December 15. "
    "Total duration 4 hr 30 min. Carbon emissions estimate: 200 kilograms."
)

LABEL_HIGH_PRICE = (
    "From 1,234 US dollars round trip total. 1 stop flight with Emirates. "
    "Leaves Dallas Fort Worth International Airport at 10:00 PM on Saturday, December 20 "
    "and arrives at Sardar Vallabhbhai Patel International Airport at 11:05 PM on Sunday, "
    "December 21. Total duration 22 hr 35 min."
)

LABEL_NO_PRICE = (
    "Select all flights. Leaves Dallas Fort Worth International Airport."
)


# ---------------------------------------------------------------------------
# _RE_PRICE
# ---------------------------------------------------------------------------

def test_price_2_stops():
    m = _RE_PRICE.search(LABEL_2_STOPS)
    assert m is not None
    assert m.group(1) == "5439"

def test_price_1_stop():
    m = _RE_PRICE.search(LABEL_1_STOP)
    assert m is not None
    assert m.group(1) == "6410"

def test_price_with_comma():
    m = _RE_PRICE.search(LABEL_HIGH_PRICE)
    assert m is not None
    assert float(m.group(1).replace(",", "")) == 1234.0

def test_price_no_match():
    assert _RE_PRICE.search(LABEL_NO_PRICE) is None


# ---------------------------------------------------------------------------
# _RE_STOPS
# ---------------------------------------------------------------------------

def test_stops_2():
    m = _RE_STOPS.search(LABEL_2_STOPS)
    assert m is not None
    assert m.group(1) == "2"

def test_stops_1():
    m = _RE_STOPS.search(LABEL_1_STOP)
    assert m is not None
    assert m.group(1) == "1"

def test_stops_nonstop():
    m = _RE_STOPS.search(LABEL_NONSTOP)
    assert m is not None
    assert m.group(0).lower().startswith("nonstop")

def test_stops_no_match():
    assert _RE_STOPS.search(LABEL_NO_PRICE) is None


# ---------------------------------------------------------------------------
# _RE_AIRLINES
# ---------------------------------------------------------------------------

def test_airlines_multiple():
    m = _RE_AIRLINES.search(LABEL_2_STOPS)
    assert m is not None
    assert "Air France" in m.group(1)
    assert "IndiGo" in m.group(1)

def test_airlines_single():
    m = _RE_AIRLINES.search(LABEL_1_STOP)
    assert m is not None
    assert m.group(1).strip() == "Qatar Airways"

def test_airlines_nonstop():
    m = _RE_AIRLINES.search(LABEL_NONSTOP)
    assert m is not None
    assert m.group(1).strip() == "United"


# ---------------------------------------------------------------------------
# _RE_DURATION
# ---------------------------------------------------------------------------

def test_duration_hours_and_minutes():
    m = _RE_DURATION.search(LABEL_2_STOPS)
    assert m is not None
    assert m.group(1).strip() == "26 hr 30 min"

def test_duration_parse_value():
    m = _RE_DURATION.search(LABEL_2_STOPS)
    assert _parse_duration(m.group(1)) == pytest.approx(26.5)

def test_duration_21h10m():
    m = _RE_DURATION.search(LABEL_1_STOP)
    assert _parse_duration(m.group(1)) == pytest.approx(21 + 10/60)

def test_duration_hours_only():
    assert _parse_duration("2 hr") == pytest.approx(2.0)

def test_duration_minutes_only():
    assert _parse_duration("45 min") == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# _parse_aria_label — end-to-end
# ---------------------------------------------------------------------------

def test_parse_2_stops_label():
    result = _parse_aria_label(LABEL_2_STOPS, "DFW", "AMD", "2026-12-20", "2027-01-10", 2)
    assert result is not None
    assert result.price_per_person == pytest.approx(5439.0)
    assert result.price_usd == pytest.approx(5439.0 * 2)
    assert result.stops == 2
    assert "Air France" in result.airline
    assert result.duration_hrs == pytest.approx(26.5)
    assert result.origin == "DFW"
    assert result.destination == "AMD"

def test_parse_1_stop_label():
    result = _parse_aria_label(LABEL_1_STOP, "DFW", "AMD", "2026-12-20", "2027-01-10", 1)
    assert result is not None
    assert result.price_per_person == pytest.approx(6410.0)
    assert result.stops == 1
    assert result.airline == "Qatar Airways"

def test_parse_nonstop_label():
    result = _parse_aria_label(LABEL_NONSTOP, "DFW", "JFK", "2026-12-15", "2027-01-05", 1)
    assert result is not None
    assert result.stops == 0
    assert result.price_per_person == pytest.approx(899.0)
    assert result.airline == "United"

def test_parse_comma_price():
    result = _parse_aria_label(LABEL_HIGH_PRICE, "DFW", "AMD", "2026-12-20", "2027-01-10", 1)
    assert result is not None
    assert result.price_per_person == pytest.approx(1234.0)

def test_parse_no_price_returns_none():
    result = _parse_aria_label(LABEL_NO_PRICE, "DFW", "AMD", "2026-12-20", "2027-01-10", 1)
    assert result is None

def test_parse_passengers_multiplied():
    result_1 = _parse_aria_label(LABEL_1_STOP, "DFW", "AMD", "2026-12-20", "2027-01-10", 1)
    result_2 = _parse_aria_label(LABEL_1_STOP, "DFW", "AMD", "2026-12-20", "2027-01-10", 2)
    assert result_1 is not None and result_2 is not None
    assert result_2.price_usd == pytest.approx(result_1.price_usd * 2)
    assert result_2.price_per_person == pytest.approx(result_1.price_per_person)
