"""Per-site scraping with retries and proxy rotation.

``jobspy.scrape_jobs`` scrapes every requested site in one call, but that makes
per-site recovery impossible: if LinkedIn fails, the whole batch is short one
site and there is no way to retry just that one. Scraping one site per call
lets each site be retried independently through a fresh proxy.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Iterable

import pandas as pd
from jobspy import scrape_jobs

from py.proxies import ProxyPool

log = logging.getLogger(__name__)

DEFAULT_SITES = ("indeed", "linkedin", "zip_recruiter", "glassdoor", "naukri", )


@dataclass(frozen=True)
class SearchQuery:
    """The search parameters shared by every site."""

    search_term: str = "Software Engineer"
    location: str = "San Francisco, CA"
    results_wanted: int = 100
    hours_old: int = 72
    country_indeed: str = "USA"


@dataclass
class SiteResult:
    site: str
    jobs: pd.DataFrame = field(default_factory=pd.DataFrame)
    attempts: int = 0
    proxy: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _scrape_once(site: str, query: SearchQuery, proxy: str | None) -> pd.DataFrame:
    return scrape_jobs(
        site_name=[site],
        search_term=query.search_term,
        location=query.location,
        results_wanted=query.results_wanted,
        hours_old=query.hours_old,
        country_indeed=query.country_indeed,
        proxies=[proxy] if proxy else None,
    )


def _failure(df: pd.DataFrame, site: str) -> str | None:
    """Return why a scrape failed, or None if it succeeded.

    jobspy reports per-site problems in ``DataFrame.attrs['errors']`` and still
    returns an empty DataFrame, so the recorded reason must be checked *before*
    the emptiness check or the real cause (a 403, a dead proxy) is lost.
    """
    errors = df.attrs.get("errors") or {}
    if errors.get(site):
        return str(errors[site])
    if df.empty:
        return "no jobs returned"
    return None


def scrape_site(
    site: str,
    query: SearchQuery,
    pool: ProxyPool | None = None,
    *,
    attempts: int = 3,
    backoff: float = 2.0,
) -> SiteResult:
    """Scrape one site, retrying through a different proxy on each failure.

    The first attempt goes out directly because it is the fastest path and
    some boards (Indeed) serve it fine. Later attempts rotate through the pool,
    discarding proxies that fail.
    """
    result = SiteResult(site=site)
    tried_proxies: set[str] = set()
    last_error = "unknown error"

    for attempt in range(1, attempts + 1):
        proxy = None if attempt == 1 else (pool.next(skip=tried_proxies) if pool else None)
        if proxy:
            tried_proxies.add(proxy)
        elif attempt > 1:
            log.debug("%s: no untried proxy left, retrying directly", site)

        result.attempts = attempt
        result.proxy = proxy
        log.info("%s: attempt %d/%d (%s)", site, attempt, attempts, proxy or "direct")

        try:
            df = _scrape_once(site, query, proxy)
        except Exception as exc:  # network errors, parsing errors, ...
            last_error = f"{type(exc).__name__}: {exc}"
            log.warning("%s: attempt %d raised %s", site, attempt, last_error)
            df = pd.DataFrame()
        else:
            error = _failure(df, site)
            if error is None:
                log.info("%s: success, %d jobs via %s", site, len(df), proxy or "direct")
                result.jobs = df
                result.error = None
                return result
            if not df.empty:
                # Some boards 403 halfway through pagination. A partial result
                # is still worth keeping rather than re-fetching from scratch.
                log.warning("%s: keeping %d jobs despite: %s", site, len(df), error)
                result.jobs = df
                result.error = None
                return result
            last_error = error

        log.warning("%s: attempt %d failed (%s)", site, attempt, last_error)
        if proxy and pool:
            pool.mark_bad(proxy)

        if attempt < attempts:
            time.sleep(backoff * attempt)

    result.error = last_error
    return result


def scrape_all(
    sites: Iterable[str] = DEFAULT_SITES,
    query: SearchQuery = SearchQuery(),
    pool: ProxyPool | None = None,
    *,
    attempts: int = 3,
    backoff: float = 2.0,
) -> list[SiteResult]:
    """Scrape every site concurrently; each site retries on its own."""
    sites = list(sites)
    with ThreadPoolExecutor(max_workers=len(sites)) as executor:
        futures = [
            executor.submit(
                scrape_site, site, query, pool, attempts=attempts, backoff=backoff
            )
            for site in sites
        ]
        return [future.result() for future in futures]


def combine(results: Iterable[SiteResult]) -> pd.DataFrame:
    """Merge successful results into one de-duplicated DataFrame."""
    frames = [result.jobs for result in results if result.ok and not result.jobs.empty]
    if not frames:
        return pd.DataFrame()

    jobs = pd.concat(frames, ignore_index=True)

    # ``id`` is unique per posting per site; fall back to the identifying
    # columns if a scraper ever returns rows without one.
    subset = [col for col in ("id",) if col in jobs.columns]
    if not subset:
        subset = [c for c in ("site", "title", "company", "location") if c in jobs.columns]
    if subset:
        jobs = jobs.drop_duplicates(subset=subset)

    if {"site", "date_posted"} <= set(jobs.columns):
        try:
            jobs = jobs.sort_values(
                by=["site", "date_posted"], ascending=[True, False], na_position="last"
            )
        except TypeError:  # mixed/unorderable values; keep scrape order
            pass

    return jobs.reset_index(drop=True)
