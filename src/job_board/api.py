"""HTTP API around the scraper.

Run it with ``job-board-api`` (or ``uvicorn job_board.api:app``). The same app is
served by the Apify Actor when the platform starts it in Standby mode, so every
endpoint here is also reachable as the Actor's container URL.

Environment variables
---------------------
``JOB_BOARD_API_TOKEN``
    When set, every scraping endpoint requires ``Authorization: Bearer <token>``.
    Ignored on Apify, where the platform authenticates the caller itself.
``JOB_BOARD_MAX_CONCURRENCY``
    Scrapes allowed to run at once (default ``2``). Each one is a thread that
    talks to several job boards, so this is a real resource limit.
``JOB_BOARD_TIMEOUT``
    Per-request wall clock limit in seconds (default ``600``).
"""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.responses import JSONResponse

from job_board import __version__
from job_board.export import to_csv_bytes, to_records
from job_board.models import (
    SUPPORTED_SITES,
    ScrapeRequest,
    ScrapeResponse,
    ScrapeReport,
)
from job_board.runner import run_scrape
from job_board.scraper import DEFAULT_SITES
from job_board.storage import timestamped_path

log = logging.getLogger("job_board.api")


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return default


def _max_concurrency() -> int:
    return max(1, _int_env("JOB_BOARD_MAX_CONCURRENCY", 2))


def _timeout_s() -> float:
    return max(1.0, _float_env("JOB_BOARD_TIMEOUT", 600.0))


# A Semaphore is bound to the event loop that first waits on it. Tests (and
# uvicorn's reloader) create more than one loop, so keep one per loop instead of
# a module-level singleton.
_semaphores: dict[int, asyncio.Semaphore] = {}


def _semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(id(loop))
    if semaphore is None:
        semaphore = _semaphores[id(loop)] = asyncio.Semaphore(_max_concurrency())
    return semaphore


def _jobspy_version() -> str:
    for distribution in ("jobspy-py", "jobspy"):
        try:
            return version(distribution)
        except PackageNotFoundError:
            continue
    return "unknown"


async def require_auth(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    """Bearer-token gate for deployments that face the public internet."""
    if os.environ.get("APIFY_IS_AT_HOME"):
        # The Apify platform validates its own API token before forwarding.
        return

    expected = os.environ.get("JOB_BOARD_API_TOKEN")
    if not expected:
        return

    scheme, _, provided = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail="missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


Auth = Annotated[None, Depends(require_auth)]

app = FastAPI(
    title="job-board",
    version=__version__,
    summary="Scrape public job boards over HTTP.",
    description=(
        "Wraps the bundled [JobSpy](https://github.com/mecodes03/JobSpy) fork. "
        "Each site is scraped in its own thread and retried independently, so one "
        "blocked board never costs you the others. Full five-site runs can take a "
        "few minutes; raise `JOB_BOARD_TIMEOUT` if you need to."
    ),
)

_SCRAPE_ERRORS: dict[int | str, dict[str, Any]] = {
    502: {"description": "Every site failed (blocked, proxies dead, upstream down)."},
    504: {"description": "Scrape exceeded JOB_BOARD_TIMEOUT."},
}


async def _report(request: ScrapeRequest) -> ScrapeReport:
    """Run the scrape on a worker thread, bounded by the semaphore and timeout."""
    started = time.perf_counter()
    log.info(
        "scrape requested: term=%r location=%r sites=%s",
        request.search_term,
        request.location,
        ",".join(request.sites),
    )
    async with _semaphore():
        try:
            report = await asyncio.wait_for(
                asyncio.to_thread(run_scrape, request.to_job()), timeout=_timeout_s()
            )
        except TimeoutError as exc:
            raise HTTPException(
                status_code=504, detail=f"scrape exceeded {_timeout_s():.0f}s"
            ) from exc
        except ValueError as exc:  # bad argument surfaced late by JobSpy
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    log.info(
        "scrape finished in %.1fs: %d jobs from %d/%d sites",
        time.perf_counter() - started,
        report.count,
        sum(result.ok for result in report.sites),
        len(report.sites),
    )
    return report


@app.get("/", include_in_schema=False)
def index() -> dict[str, Any]:
    return {
        "name": "job-board",
        "version": __version__,
        "docs": "/docs",
        "openapi": "/openapi.json",
        "endpoints": ["/health", "/sites", "/scrape", "/scrape.csv"],
    }


@app.get("/health", summary="Liveness probe")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": __version__,
        "jobspy": _jobspy_version(),
        "sites": list(SUPPORTED_SITES),
        "default_sites": list(DEFAULT_SITES),
    }


@app.get("/sites", summary="Supported job boards")
def sites() -> dict[str, list[str]]:
    return {"supported": list(SUPPORTED_SITES), "default": list(DEFAULT_SITES)}


@app.post("/scrape", response_model=ScrapeResponse, responses=_SCRAPE_ERRORS, summary="Scrape and return JSON")
async def scrape(request: ScrapeRequest, _: Auth = None) -> ScrapeResponse | JSONResponse:
    report = await _report(request)
    jobs = to_records(report.jobs)
    response = ScrapeResponse.from_report(report, jobs)

    if report.all_failed:
        # Same body shape as a success so clients parse one thing.
        return JSONResponse(status_code=502, content=response.model_dump())

    return response


@app.get("/scrape", response_model=ScrapeResponse, responses=_SCRAPE_ERRORS, summary="Scrape via query string")
async def scrape_get(
    request: Annotated[ScrapeRequest, Query()], _: Auth = None
) -> ScrapeResponse | JSONResponse:
    """Same as ``POST /scrape`` but callable from a browser or plain ``curl``.

    Repeat ``sites`` to scrape more than one board: ``?sites=indeed&sites=linkedin``.
    """
    return await scrape(request)


@app.post(
    "/scrape.csv",
    response_class=Response,
    responses={
        **_SCRAPE_ERRORS,
        200: {"content": {"text/csv": {}}, "description": "The scraped jobs as CSV."},
    },
    summary="Scrape and download a CSV",
)
async def scrape_csv(request: ScrapeRequest, _: Auth = None) -> Response:
    report = await _report(request)
    if report.count == 0:
        status = 502 if report.all_failed else 404
        raise HTTPException(
            status_code=status,
            detail=(
                "every site failed; see the logs"
                if report.all_failed
                else "no jobs matched the query"
            ),
        )

    filename = timestamped_path().name
    return Response(
        content=to_csv_bytes(report.jobs),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Job-Count": str(report.count),
        },
    )
