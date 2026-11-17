"""Free proxy discovery, validation and rotation.

The pool is deliberately small: free proxies die constantly, so it is better
to keep a handful of proxies that answered recently than a huge list of
unverified ones. A proxy that fails a scrape is discarded on the spot so the
next retry uses a different one.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

log = logging.getLogger(__name__)

PROXY_LIST_URL = (
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http"
    "&timeout=10000&country=all&ssl=all&anonymity=all"
)
PROXY_TEST_URL = "https://httpbin.org/ip"


def fetch_candidates(timeout: float = 10.0) -> list[str]:
    """Download the raw proxy list from ProxyScrape."""
    try:
        response = requests.get(PROXY_LIST_URL, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:
        log.warning("could not download proxy list: %s", exc)
        return []

    # ProxyScrape separates entries with CRLF or LF depending on the day.
    return [line.strip() for line in response.text.splitlines() if line.strip()]


def test_proxy(proxy: str, timeout: float = 5.0) -> str | None:
    """Return the proxy as a URL if it answers, otherwise None."""
    proxy_url = f"http://{proxy}"
    try:
        response = requests.get(
            PROXY_TEST_URL,
            proxies={"http": proxy_url, "https": proxy_url},
            timeout=timeout,
        )
    except requests.RequestException:
        return None
    return proxy_url if response.ok else None


class ProxyPool:
    """A thread-safe, rotating pool of validated proxies."""

    def __init__(self, target_size: int = 6, max_test: int = 120, workers: int = 30) -> None:
        self.target_size = target_size
        self.max_test = max_test
        self.workers = workers
        self._proxies: list[str] = []
        self._cursor = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        with self._lock:
            return len(self._proxies)

    def refresh(self) -> int:
        """(Re)build the pool from a fresh proxy list. Returns the pool size."""
        candidates = fetch_candidates()
        if not candidates:
            return 0

        log.info("testing up to %d of %d proxies", min(self.max_test, len(candidates)), len(candidates))
        working: list[str] = []
        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            futures = [executor.submit(test_proxy, proxy) for proxy in candidates[: self.max_test]]
            for future in as_completed(futures):
                result = future.result()
                if result:
                    working.append(result)
                if len(working) >= self.target_size:
                    break

        with self._lock:
            self._proxies = working
            self._cursor = 0
        return len(working)

    def next(self, skip: set[str] | None = None) -> str | None:
        """Return the next proxy not in ``skip``, or None if none is left."""
        skip = skip or set()
        with self._lock:
            candidates = [proxy for proxy in self._proxies if proxy not in skip]
            if not candidates:
                return None
            proxy = candidates[self._cursor % len(candidates)]
            self._cursor += 1
            return proxy

    def mark_bad(self, proxy: str) -> None:
        """Remove a proxy that failed, so it is never handed out again."""
        with self._lock:
            if proxy in self._proxies:
                self._proxies.remove(proxy)
