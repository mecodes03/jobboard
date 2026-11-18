"""Apify Actor entrypoint.

One image, two behaviours, chosen at runtime:

Standby (``ACTOR_STANDBY_PORT`` is set by the platform)
    Stay up and serve :mod:`jobboard.api` on the port Apify hands us. The Actor
    then behaves like a normal REST API at its container URL, with Apify doing
    authentication. Enable it with ``usesStandbyMode`` in ``.actor/actor.json``.

Regular run (everything else)
    Read ``INPUT``, scrape once, push every job to the default dataset and save
    the same rows as ``OUTPUT.csv`` in the key-value store. This is the classic
    Actor contract: ``apify call`` / schedules / the Console all use it.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from apify import Actor
from pydantic import ValidationError

from jobboard.export import to_csv_bytes, to_records
from jobboard.models import ScrapeRequest, ScrapeResponse
from jobboard.runner import run_scrape

CSV_KEY = "OUTPUT"
REPORT_KEY = "REPORT"

# Actor input schema uses camelCase; the shared models use snake_case.
_INPUT_FIELDS: dict[str, str] = {
    "searchTerm": "search_term",
    "location": "location",
    "sites": "sites",
    "resultsWanted": "results_wanted",
    "hoursOld": "hours_old",
    "countryIndeed": "country_indeed",
    "attempts": "attempts",
    "backoff": "backoff",
    "useProxies": "use_proxies",
    "poolSize": "pool_size",
}


def request_from_input(data: dict[str, Any] | None) -> ScrapeRequest:
    """Map Apify's camelCase input onto :class:`ScrapeRequest`."""
    payload: dict[str, Any] = {}
    for key, value in (data or {}).items():
        field = _INPUT_FIELDS.get(key)
        if field is not None and value is not None:
            payload[field] = value
    return ScrapeRequest.model_validate(payload)


async def _serve_standby() -> None:
    import uvicorn

    from jobboard.api import app

    port = Actor.configuration.web_server_port
    Actor.log.info("standby mode: serving the API on port %d", port)
    await Actor.set_status_message(f"API listening on port {port}")

    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="0.0.0.0",  # noqa: S104 - the platform routes to the container
            port=port,
            log_config=None,  # keep the Actor's logging configuration
            access_log=False,
        )
    )
    await server.serve()


async def act() -> None:
    """Body of the Actor, assuming an already-initialised ``Actor`` context."""
    if os.environ.get("ACTOR_STANDBY_PORT"):
        await _serve_standby()
        return

    data = await Actor.get_input() or {}
    try:
        request = request_from_input(data)
    except ValidationError as exc:
        await Actor.fail(status_message=f"invalid input: {exc}")
        return

    Actor.log.info(
        "scraping %r in %r from %s",
        request.search_term,
        request.location,
        ", ".join(request.sites),
    )
    report = await asyncio.to_thread(run_scrape, request.to_job())
    rows = to_records(report.jobs)
    summary = ScrapeResponse.from_report(report, rows)

    if rows:
        await Actor.push_data(rows)
    await Actor.set_value(
        CSV_KEY, to_csv_bytes(report.jobs), content_type="text/csv; charset=utf-8"
    )
    await Actor.set_value(
        REPORT_KEY,
        summary.model_dump(exclude={"jobs"}),
        content_type="application/json; charset=utf-8",
    )

    for site in summary.sites:
        if site.ok:
            Actor.log.info("%-14s %4d jobs (%d attempts)", site.site, site.jobs, site.attempts)
        else:
            Actor.log.warning("%-14s FAILED: %s", site.site, site.error)

    Actor.log.info(
        "pushed %d jobs (%d/%d sites ok) in %.1fs",
        len(rows),
        sum(site.ok for site in summary.sites),
        len(summary.sites),
        report.elapsed_s,
    )


async def main() -> None:
    async with Actor:
        await act()


def run() -> int:
    asyncio.run(main())
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
