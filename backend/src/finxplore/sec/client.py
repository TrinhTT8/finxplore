"""Minimal SEC EDGAR client that follows the SEC fair-access rules.

- Declares a descriptive User-Agent with a contact email (required by the SEC).
- Caps the request rate (SEC allows at most 10 requests/second).
- Retries with exponential backoff on 429 / 5xx.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import requests

from finxplore.config import get_settings

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
BULK_COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"


def pad_cik(cik: str | int) -> str:
    return str(int(cik)).zfill(10)


class SecClient:
    def __init__(
        self,
        user_agent: str | None = None,
        max_rps: float | None = None,
        max_retries: int = 3,
        session: requests.Session | None = None,
    ) -> None:
        settings = get_settings()
        user_agent = user_agent or settings.sec_user_agent
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC_USER_AGENT must be set to 'AppName contact@email' (SEC fair-access rule)"
            )
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
        self._min_interval = 1.0 / (max_rps or settings.sec_max_rps)
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._last_request = 0.0

    def _throttle(self) -> None:
        with self._lock:
            wait = self._min_interval - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            self._last_request = time.monotonic()

    def get_json(self, url: str) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            self._throttle()
            resp = self._session.get(url, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == self._max_retries:
                    resp.raise_for_status()
                time.sleep(2**attempt)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError("unreachable")

    def companyfacts(self, cik: str | int) -> dict[str, Any]:
        return self.get_json(COMPANYFACTS_URL.format(cik=pad_cik(cik)))

    def submissions(self, cik: str | int) -> dict[str, Any]:
        return self.get_json(SUBMISSIONS_URL.format(cik=pad_cik(cik)))
