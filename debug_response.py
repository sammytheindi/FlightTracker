"""
Debug script: fetch one Google Flights result and inspect the raw HTML
to see what CSS selectors are actually present vs what fast-flights expects.
"""

import sys
from fast_flights.filter import TFSData
from fast_flights import FlightData, Passengers
from fast_flights.core import fetch

flight_data = [
    FlightData(date="2026-12-20", from_airport="DFW", to_airport="AMD"),
    FlightData(date="2027-01-10", from_airport="AMD", to_airport="DFW"),
]
passengers = Passengers(adults=2)

tfs = TFSData.from_interface(
    flight_data=flight_data,
    trip="round-trip",
    passengers=passengers,
    seat="economy",
)

params = {
    "tfs": tfs.as_b64().decode("utf-8"),
    "hl": "en",
    "tfu": "EgQIABABIgA",
    "curr": "",
}

print("Fetching from Google Flights...")
res = fetch(params)
print(f"Status: {res.status_code}")
print(f"Response length: {len(res.text)} chars\n")

# Save full HTML for inspection
with open("debug_response.html", "w") as f:
    f.write(res.text)
print("Full HTML saved to debug_response.html")

# Check which CSS selectors actually match
from selectolax.lexbor import LexborHTMLParser
parser = LexborHTMLParser(res.text)

selectors = {
    "flight containers": 'div[jsname="IWWDBc"], div[jsname="YdtKid"]',
    "list items": "ul.Rk10dc li",
    "name":       "div.sSHqwe.tPgKwe.ogfYpf span",
    "stops":      ".BbR8Ec .ogfYpf",
    "duration":   "li div.Ak5kof div",
    "price":      ".YMlIz.FpEdX",
    "dep/arr":    "span.mv1WYe div",
}

print("\n--- CSS selector match counts ---")
for label, sel in selectors.items():
    matches = parser.css(sel)
    print(f"  {label:20s} ({sel[:40]}): {len(matches)} match(es)")
    if matches and label in ("name", "stops", "duration", "price"):
        print(f"    First text: {matches[0].text(strip=True)!r}")
