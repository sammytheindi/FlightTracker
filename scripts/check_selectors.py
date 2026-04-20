#!/usr/bin/env python3
"""
Selector health check for Google Flights parsing.

Makes one real request to Google Flights and verifies that every regex
pattern we depend on matches expected data. Run this weekly (or whenever
searches return empty results) to detect Google breaking our parser before
it affects a full search run.

Usage:
    python scripts/check_selectors.py
    make check-selectors

Exit codes:
    0 — all patterns healthy
    1 — one or more patterns broken (output shows which ones)
"""

import re
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from selectolax.lexbor import LexborHTMLParser
from fast_flights import FlightData, Passengers
from fast_flights.filter import TFSData
from fast_flights.core import fetch
from src.api.google_flights import (
    _RE_PRICE,
    _RE_STOPS,
    _RE_AIRLINES,
    _RE_DURATION,
    _parse_aria_label,
    _parse_html,
)

# ── Probe flight: one combo, just enough to get real results ──────────────
PROBE_ORIGIN      = "DFW"
PROBE_DESTINATION = "AMD"
PROBE_DEPART      = "2026-12-15"
PROBE_RETURN      = "2027-01-05"
PROBE_PASSENGERS  = 1


def _fetch_probe() -> str:
    tfs = TFSData.from_interface(
        flight_data=[
            FlightData(date=PROBE_DEPART, from_airport=PROBE_ORIGIN, to_airport=PROBE_DESTINATION),
            FlightData(date=PROBE_RETURN, from_airport=PROBE_DESTINATION, to_airport=PROBE_ORIGIN),
        ],
        trip="round-trip",
        passengers=Passengers(adults=PROBE_PASSENGERS),
        seat="economy",
    )
    params = {"tfs": tfs.as_b64().decode("utf-8"), "hl": "en", "tfu": "EgQIABABIgA", "curr": ""}
    res = fetch(params)
    assert res.status_code == 200, f"HTTP {res.status_code}"
    return res.text


def _check(label: str, name: str, pattern: re.Pattern) -> tuple[bool, str]:
    """Return (passed, detail_message)."""
    m = pattern.search(label)
    if m:
        return True, f"✓  {name:12s} → {m.group(0)!r}"
    return False, f"✗  {name:12s} — no match in:\n     {label[:200]!r}"


def main() -> int:
    print(f"Fetching probe: {PROBE_ORIGIN}→{PROBE_DESTINATION}  "
          f"dep {PROBE_DEPART}  ret {PROBE_RETURN}\n")

    try:
        html = _fetch_probe()
    except Exception as e:
        print(f"[FAIL] Could not fetch from Google Flights: {e}")
        return 1

    parser = LexborHTMLParser(html)
    cards = parser.css("div.JMc5Xc[aria-label]")

    # ── 1. Card container selector ────────────────────────────────────────
    print(f"Flight cards found: {len(cards)}")
    if not cards:
        # Save HTML and scan for divs with aria-labels to find the new element name
        html_path = Path("debug_check_selectors.html")
        html_path.write_text(html)
        print(f"\n[FAIL] Selector 'div.JMc5Xc[aria-label]' returned 0 results.")
        print(f"       Raw HTML saved to: {html_path} ({len(html):,} chars)")

        # Scan for any divs that have aria-labels containing flight-like content
        print("\n--- Divs with aria-labels mentioning 'US dollars' (candidate selectors) ---")
        candidates = parser.css("div[aria-label]")
        found = [(n.tag, n.attributes.get("class",""), n.attributes.get("aria-label","")[:120])
                 for n in candidates
                 if "US dollars" in n.attributes.get("aria-label", "")]
        if found:
            for tag, cls, label in found[:5]:
                print(f"  <{tag} class={cls!r}>")
                print(f"    aria-label: {label!r}\n")
            print(f"  Update the selector in src/api/google_flights.py _parse_html()")
        else:
            print("  No divs with 'US dollars' in aria-label found.")
            print("  Google may be returning a consent/CAPTCHA page.")
            print(f"  Open {html_path} in a browser to inspect the response.")
        return 1

    # Use the first card's aria-label for pattern checks
    label = cards[0].attributes.get("aria-label", "")
    print(f"\nSample aria-label (first card):\n  {label[:300]!r}\n")

    # ── 2. Regex pattern checks ───────────────────────────────────────────
    checks = [
        ("price",    _RE_PRICE),
        ("stops",    _RE_STOPS),
        ("airlines", _RE_AIRLINES),
        ("duration", _RE_DURATION),
    ]

    failures = []
    print("Regex pattern health:")
    for name, pattern in checks:
        passed, msg = _check(label, name, pattern)
        print(f"  {msg}")
        if not passed:
            failures.append(name)

    # ── 3. End-to-end parse check ─────────────────────────────────────────
    print("\nEnd-to-end parse (first 3 results):")
    results = _parse_html(html, PROBE_ORIGIN, PROBE_DESTINATION,
                          PROBE_DEPART, PROBE_RETURN, PROBE_PASSENGERS)
    if not results:
        print("  [FAIL] _parse_html returned 0 results")
        failures.append("end-to-end")
    else:
        for r in results[:3]:
            print(f"  {r}")

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    if failures:
        print(f"[FAIL] {len(failures)} pattern(s) broken: {', '.join(failures)}")
        print("       Open debug_response.html (run python debug_response.py first)")
        print("       and find the new format, then update the regex in:")
        print("       src/api/google_flights.py")
        return 1

    print("[PASS] All patterns healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
