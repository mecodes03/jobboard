"""One scrape end to end, independent of how it was triggered.

The CLI, the HTTP API and the Apify Actor all call :func:`run_scrape`; they only
differ in how they parse arguments and where they put the result.
"""

from __future__ import annotations

import logging
import time

from jobboard.models import ScrapeJob, ScrapeReport
from jobboard.proxies import ProxyPool
from jobboard.scraper import combine, scrape_all

log = logging.getLogger("jobboard.runner")


def build_pool(job: ScrapeJob) -> ProxyPool | None:
    """Validate a proxy pool when retries could actually use one, else None."""
    if not job.use_proxies or job.attempts < 2:
        return None

    pool = ProxyPool(target_size=job.pool_size)
    log.info("collecting proxies...")
    available = pool.refresh()
    log.info("%d working proxies in the pool", available)
    if not available:
        log.warning("no working proxies found; retries will use a direct connection")
    return pool


def run_scrape(job: ScrapeJob) -> ScrapeReport:
    """Scrape every requested site concurrently and merge the results."""
    started = time.perf_counter()
    pool = build_pool(job)

    results = scrape_all(
        job.sites, job.query, pool, attempts=job.attempts, backoff=job.backoff
    )
    jobs = combine(results)

    return ScrapeReport(jobs=jobs, sites=results, elapsed_s=time.perf_counter() - started)
