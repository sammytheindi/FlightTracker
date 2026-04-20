"""Playwright-based fetcher for Google Flights.

Launches a single headless Chromium browser for the lifetime of a search run,
reusing it across all page fetches. Each fetch opens a new tab, loads the
results, captures the HTML, then closes the tab.

Waits for [aria-label*="US dollars"] to appear before returning HTML —
the same stable accessibility string our parser already depends on.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_RESULTS_TIMEOUT_MS = 20_000


@dataclass
class FetchResponse:
    status_code: int
    text: str
    elapsed_s: float = 0.0   # how long the page fetch took


@dataclass
class SessionStats:
    """Telemetry collected over the lifetime of a BrowserSession."""
    fetches_attempted: int = 0
    fetches_succeeded: int = 0   # got flight results
    fetches_empty: int = 0       # page loaded but no results (bot detection / no flights)
    fetches_failed: int = 0      # exception or timeout
    total_elapsed_s: float = 0.0
    durations: list[float] = field(default_factory=list)

    @property
    def fetches_done(self) -> int:
        return self.fetches_succeeded + self.fetches_empty + self.fetches_failed

    @property
    def avg_elapsed_s(self) -> float:
        return (sum(self.durations) / len(self.durations)) if self.durations else 0.0

    @property
    def success_rate(self) -> float:
        return (self.fetches_succeeded / self.fetches_done * 100) if self.fetches_done else 0.0


class BrowserSession:
    """
    A reusable Playwright browser session.

    Open once at the start of a search run, call fetch() for each request,
    then close() when done. Collects timing and success telemetry via .stats.

    Usage:
        with BrowserSession() as session:
            response = session.fetch(params)
        print(session.stats)
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._playwright = None
        self._browser = None
        self._context = None
        self.stats = SessionStats()
        self._opened_at: Optional[float] = None

    def open(self) -> None:
        """Launch the browser. Must be called before fetch()."""
        t = time.monotonic()
        self._loop = asyncio.new_event_loop()
        self._loop.run_until_complete(self._async_open())
        elapsed = time.monotonic() - t
        self._opened_at = time.monotonic()
        logger.info("Browser launched (%.1fs)", elapsed)

    def fetch(self, params: dict, retries: int = 1, retry_delay_s: float = 8.0) -> FetchResponse:
        """
        Fetch one Google Flights results page and record telemetry.

        If the page loads but returns no results (bot detection / timeout),
        waits retry_delay_s and tries once more before giving up.
        """
        assert self._loop and self._browser, "Call open() before fetch()"
        url = (
            "https://www.google.com/travel/flights?"
            + "&".join(f"{k}={v}" for k, v in params.items())
        )
        self.stats.fetches_attempted += 1
        t = time.monotonic()

        for attempt in range(1 + retries):
            try:
                html, got_results = self._loop.run_until_complete(self._async_fetch(url))
                elapsed = time.monotonic() - t

                if got_results:
                    self.stats.fetches_succeeded += 1
                    self.stats.durations.append(elapsed)
                    self.stats.total_elapsed_s += elapsed
                    return FetchResponse(status_code=200, text=html, elapsed_s=elapsed)

                # No results — retry if attempts remain
                if attempt < retries:
                    logger.info(
                        "No results on attempt %d/%d — retrying in %.0fs...",
                        attempt + 1, 1 + retries, retry_delay_s,
                    )
                    time.sleep(retry_delay_s)
                else:
                    self.stats.fetches_empty += 1
                    self.stats.durations.append(elapsed)
                    self.stats.total_elapsed_s += elapsed
                    return FetchResponse(status_code=200, text=html, elapsed_s=elapsed)

            except Exception as e:
                elapsed = time.monotonic() - t
                if attempt < retries:
                    logger.info("Fetch error on attempt %d/%d (%s) — retrying...", attempt + 1, 1 + retries, e)
                    time.sleep(retry_delay_s)
                else:
                    self.stats.fetches_failed += 1
                    self.stats.total_elapsed_s += elapsed
                    logger.warning("Fetch failed after %.1fs: %s", elapsed, e)
                    return FetchResponse(status_code=500, text="", elapsed_s=elapsed)

        # unreachable, but satisfies type checker
        return FetchResponse(status_code=500, text="", elapsed_s=0.0)

    def close(self) -> None:
        """Close the browser and log a summary."""
        if self._loop:
            self._loop.run_until_complete(self._async_close())
            self._loop.close()
            self._loop = None
        total = time.monotonic() - self._opened_at if self._opened_at else 0
        logger.info(
            "Browser closed. %d/%d fetches succeeded (%.0f%%) | "
            "avg %.1fs/page | total session %.0fs",
            self.stats.fetches_succeeded,
            self.stats.fetches_done,
            self.stats.success_rate,
            self.stats.avg_elapsed_s,
            total,
        )

    def __enter__(self) -> "BrowserSession":
        self.open()
        return self

    def __exit__(self, *_) -> None:
        self.close()

    async def _async_open(self) -> None:
        from playwright.async_api import async_playwright  # lazy import
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._context = await self._browser.new_context(
            locale="en-US",
            timezone_id="America/Chicago",
        )

    async def _async_fetch(self, url: str) -> tuple[str, bool]:
        """Returns (html, got_results)."""
        from playwright.async_api import TimeoutError as PlaywrightTimeout  # lazy import

        page = await self._context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded")

            if "consent.google.com" in page.url:
                logger.debug("Consent page — accepting...")
                await page.click('button:has-text("Accept all")')
                await page.wait_for_load_state("domcontentloaded")

            got_results = False
            try:
                await page.wait_for_selector(
                    '[aria-label*="US dollars"]',
                    timeout=_RESULTS_TIMEOUT_MS,
                )
                got_results = True
            except PlaywrightTimeout:
                logger.warning(
                    "Timed out waiting for flight results (%dms) — "
                    "page may be empty or bot-detected.",
                    _RESULTS_TIMEOUT_MS,
                )

            return await page.content(), got_results
        finally:
            await page.close()

    async def _async_close(self) -> None:
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()


def playwright_fetch(params: dict) -> FetchResponse:
    """Single fetch — opens and closes the browser each time. Use BrowserSession for batches."""
    with BrowserSession() as session:
        return session.fetch(params)
