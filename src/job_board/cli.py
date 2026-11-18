"""Command line entry point."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from job_board.models import ScrapeJob
from job_board.runner import run_scrape
from job_board.scraper import DEFAULT_SITES, SearchQuery
from job_board.storage import write_jobs

log = logging.getLogger("job_board")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job_board",
        description="Scrape job boards and save the results to a timestamped CSV.",
    )
    parser.add_argument("--search-term", default="Software Engineer", help="job title to search for")
    parser.add_argument("--location", default="San Francisco, CA", help="where to search")
    parser.add_argument(
        "--results-wanted", type=int, default=100, help="results per site (default: 100)"
    )
    parser.add_argument("--hours-old", type=int, default=72, help="only postings newer than N hours")
    parser.add_argument("--country-indeed", default="USA", help="country for Indeed")
    parser.add_argument(
        "--sites",
        nargs="+",
        default=list(DEFAULT_SITES),
        metavar="SITE",
        help=f"sites to scrape (default: {' '.join(DEFAULT_SITES)})",
    )
    parser.add_argument(
        "--attempts", type=int, default=3, help="attempts per site, each on a new proxy (default: 3)"
    )
    parser.add_argument("--backoff", type=float, default=2.0, help="seconds between attempts")
    parser.add_argument(
        "--no-proxies", action="store_true", help="never use proxies (debugging / fast runs)"
    )
    parser.add_argument("--pool-size", type=int, default=6, help="proxies to keep validated (default: 6)")
    parser.add_argument(
        "--output-dir", type=Path, default=Path.cwd(), help="where to write the CSV (default: cwd)"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logging")
    return parser


def _configure_logging(verbose: bool) -> None:
    handler = logging.StreamHandler()
    if not verbose:
        # jobspy logs every blocked request and every unparsable posting. We
        # summarise failures ourselves, and it resets its own level inside
        # scrape_jobs(), so drop its records at the handler instead.
        handler.addFilter(lambda record: not record.name.startswith("jobspy"))
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(message)s",
        handlers=[handler],
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose)

    if args.attempts < 1:
        log.error("--attempts must be at least 1")
        return 2

    query = SearchQuery(
        search_term=args.search_term,
        location=args.location,
        results_wanted=args.results_wanted,
        hours_old=args.hours_old,
        country_indeed=args.country_indeed,
    )

    job = ScrapeJob(
        query=query,
        sites=tuple(args.sites),
        attempts=args.attempts,
        backoff=args.backoff,
        use_proxies=not args.no_proxies,
        pool_size=args.pool_size,
    )
    report = run_scrape(job)

    for result in report.sites:
        if result.ok:
            log.info("%-14s %4d jobs  (%d attempt%s)", result.site, len(result.jobs),
                     result.attempts, "s" if result.attempts != 1 else "")
        else:
            log.warning("%-14s FAILED after %d attempt%s: %s", result.site,
                        result.attempts, "s" if result.attempts != 1 else "", result.error)

    if report.jobs.empty:
        log.error("no jobs found on any site; nothing written")
        return 1

    path = write_jobs(report.jobs, args.output_dir)
    print(f"Saved {len(report.jobs)} jobs to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
