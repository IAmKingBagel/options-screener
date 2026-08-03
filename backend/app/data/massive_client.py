"""Massive.com REST API client for options chain snapshots."""

from __future__ import annotations

import logging
import time
from typing import Any, Optional
from urllib.parse import urljoin

import httpx
import certifi

try:
    import truststore

    truststore.inject_into_ssl()
except ImportError:
    pass

from app.config import get_settings

logger = logging.getLogger(__name__)


class MassiveAPIError(Exception):
    """Raised when the Massive API returns an error response."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class MassiveClient:
    """
    Thin HTTP client for Massive options endpoints.

    Field paths are based on documented response shapes; inspect live responses
    when Massive changes schemas.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
        max_retries: int = 3,
    ):
        settings = get_settings()
        self.api_key = api_key or settings.massive_api_key
        self.base_url = (base_url or settings.massive_base_url).rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        # Use certifi bundle explicitly — fixes SSL errors on some Windows/Python installs.
        self._verify = certifi.where()

    def _http_client(self) -> httpx.Client:
        return httpx.Client(timeout=self.timeout, verify=self._verify)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise MassiveAPIError(
                "MASSIVE_API_KEY is not configured. Set it in your .env file."
            )
        return {"Authorization": f"Bearer {self.api_key}"}

    def _request(self, method: str, path: str, params: Optional[dict[str, Any]] = None) -> dict:
        url = urljoin(f"{self.base_url}/", path.lstrip("/"))
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            started = time.perf_counter()
            try:
                with self._http_client() as client:
                    response = client.request(
                        method,
                        url,
                        headers=self._headers(),
                        params=params,
                    )
                elapsed_ms = (time.perf_counter() - started) * 1000
                logger.info(
                    "Massive API %s %s -> %s (%.0fms)",
                    method,
                    path,
                    response.status_code,
                    elapsed_ms,
                )

                if response.status_code == 429 and attempt < self.max_retries - 1:
                    # Starter plans are tight on RPM; wait longer than 1/2/4s.
                    retry_after = response.headers.get("Retry-After")
                    try:
                        wait = float(retry_after) if retry_after else (5 * (attempt + 1))
                    except ValueError:
                        wait = 5 * (attempt + 1)
                    wait = min(max(wait, 5.0), 60.0)
                    logger.warning(
                        "Massive API 429 on %s — waiting %.0fs (attempt %s/%s)",
                        path,
                        wait,
                        attempt + 1,
                        self.max_retries,
                    )
                    time.sleep(wait)
                    continue

                if response.status_code == 429:
                    raise MassiveAPIError(
                        "Massive rate limit hit (too many API calls per minute). "
                        "Wait about a minute, then try again. Refresh Open Marks "
                        "now uses one chain fetch per stock — avoid Force Refresh "
                        "on many tickers at once.",
                        status_code=429,
                    )

                if response.status_code >= 400:
                    raise MassiveAPIError(
                        f"Massive API error {response.status_code}: {response.text[:500]}",
                        status_code=response.status_code,
                    )

                try:
                    return response.json()
                except ValueError as exc:
                    raise MassiveAPIError(
                        f"Massive API returned non-JSON response for {path}: "
                        f"{response.text[:200]}"
                    ) from exc
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise MassiveAPIError(f"HTTP error contacting Massive API: {exc}") from exc

        raise MassiveAPIError(f"Massive API request failed after retries: {last_error}")

    def get_option_chain_snapshot(
        self,
        underlying_symbol: str,
        params: Optional[dict[str, Any]] = None,
        *,
        max_pages: int = 4,
    ) -> dict[str, Any]:
        """
        Fetch option chain snapshot, following pagination via next_url.

        Endpoint: GET /v3/snapshot/options/{underlyingAsset}

        Caps pages so liquid underlyings like SPY do not hang the browser.
        Default max_pages=4 => up to 1000 contracts (limit 250).
        """
        symbol = underlying_symbol.upper()
        path = f"/v3/snapshot/options/{symbol}"
        query = dict(params or {})
        if "limit" not in query:
            query["limit"] = 250

        payload = self._request("GET", path, params=query)
        results = list(payload.get("results") or [])
        pages_fetched = 1
        truncated = False

        next_url = payload.get("next_url")
        while next_url and pages_fetched < max_pages:
            next_path = next_url
            if next_url.startswith(self.base_url):
                next_path = next_url[len(self.base_url) :]
            page = self._request("GET", next_path)
            results.extend(page.get("results") or [])
            next_url = page.get("next_url")
            pages_fetched += 1

        if next_url:
            truncated = True

        return {
            "status": payload.get("status"),
            "request_id": payload.get("request_id"),
            "results": results,
            "truncated": truncated,
            "pages_fetched": pages_fetched,
        }

    def get_underlying_price(self, underlying_symbol: str) -> Optional[float]:
        """Previous-session close for the underlying (fast, one request)."""
        return self.get_underlying_previous_close(underlying_symbol)

    def get_underlying_previous_close(self, underlying_symbol: str) -> Optional[float]:
        """
        Fetch previous session close for the underlying.

        Endpoint: GET /v2/aggs/ticker/{symbol}/prev
        Used when options snapshots omit underlying_asset.price (common on Starter).
        """
        symbol = underlying_symbol.upper()
        payload = self._request("GET", f"/v2/aggs/ticker/{symbol}/prev")
        results = payload.get("results") or []
        if not results:
            return None
        close = results[0].get("c")
        return float(close) if close is not None else None

    def get_underlying_daily_bars(
        self,
        underlying_symbol: str,
        start: str,
        end: str,
        *,
        limit: int = 50000,
    ) -> list[dict[str, Any]]:
        """
        Daily OHLC bars for an underlying.

        Endpoint: GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}
        Returns list of {t, o, h, l, c, v, ...} oldest-first.
        """
        symbol = underlying_symbol.upper()
        path = f"/v2/aggs/ticker/{symbol}/range/1/day/{start}/{end}"
        payload = self._request(
            "GET",
            path,
            params={"adjusted": "true", "sort": "asc", "limit": limit},
        )
        return list(payload.get("results") or [])
