"""Abstract base for flight search adapters and shared data models."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FlightResult:
    """A single flight offer returned by a search."""

    origin: str
    destination: str
    depart_date: str          # ISO date string: YYYY-MM-DD
    return_date: str          # ISO date string: YYYY-MM-DD
    price_usd: float          # Total price for all passengers
    price_per_person: float   # price_usd / passengers
    airline: str              # Primary marketing carrier name
    stops: int                # Number of stops (0 = nonstop)
    duration_hrs: float       # Total outbound journey duration in hours
    fetched_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def __str__(self) -> str:
        stops_label = "nonstop" if self.stops == 0 else f"{self.stops} stop(s)"
        return (
            f"{self.origin}→{self.destination} "
            f"dep {self.depart_date} / ret {self.return_date} | "
            f"${self.price_per_person:.0f}/person ({stops_label}, {self.airline})"
        )


class FlightSearchAdapter(ABC):
    """
    Abstract base class for flight search providers.

    Implement this interface to add a new data source (Amadeus, SerpAPI, etc.).
    All adapters must be stateless per-search call.
    """

    @abstractmethod
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
        """
        Search for round-trip flight offers.

        Args:
            origin: IATA airport code for departure (e.g. "DFW")
            destination: IATA airport code for arrival (e.g. "AMD")
            depart_date: Outbound date as YYYY-MM-DD
            return_date: Return date as YYYY-MM-DD
            passengers: Number of adult passengers
            cabin_class: One of ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST
            max_results: Maximum number of offers to return

        Returns:
            List of FlightResult, sorted cheapest first. Empty list if no results.
        """
