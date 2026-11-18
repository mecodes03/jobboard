"""Value objects shared by the CLI, the HTTP API and the Apify Actor.

Keeping the request/response shapes in one module means the three front doors
cannot drift apart: a limit added here is enforced everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from jobspy.model import Site
from pydantic import BaseModel, ConfigDict, Field, field_validator

from jobboard.scraper import DEFAULT_SITES, SearchQuery, SiteResult

# Derived from the bundled JobSpy fork so the two lists can never drift.
# Google is excluded: its scraper needs ``google_search_term`` rather than
# ``search_term``, so it cannot share the same request model.
SUPPORTED_SITES: tuple[str, ...] = tuple(s.value for s in Site if s is not Site.GOOGLE)


@dataclass(frozen=True, slots=True)
class ScrapeJob:
    """A fully-resolved scrape, ready to hand to :func:`jobboard.runner.run_scrape`."""

    query: SearchQuery = SearchQuery()
    sites: tuple[str, ...] = DEFAULT_SITES
    attempts: int = 3
    backoff: float = 2.0
    use_proxies: bool = True
    pool_size: int = 6


@dataclass(slots=True)
class ScrapeReport:
    """What a scrape produced: the merged rows plus a per-site outcome."""

    jobs: pd.DataFrame
    sites: list[SiteResult] = field(default_factory=list)
    elapsed_s: float = 0.0

    @property
    def count(self) -> int:
        return len(self.jobs)

    @property
    def all_failed(self) -> bool:
        """True when no site produced a usable result (upstream problem)."""
        return not any(result.ok for result in self.sites)


class ScrapeRequest(BaseModel):
    """Body of ``POST /scrape`` and the source of Actor input validation."""

    model_config = ConfigDict(extra="forbid")

    search_term: str = Field(
        default="Software Engineer", min_length=1, max_length=200, examples=["Data Engineer"]
    )
    location: str = Field(
        default="San Francisco, CA", min_length=1, max_length=200, examples=["Austin, TX"]
    )
    # A plain default (not default_factory) keeps ``Depends(ScrapeRequest)``
    # working for the GET variant: FastAPI introspects the signature and would
    # otherwise pass the factory object itself as the value.
    sites: list[str] = Field(default=list(DEFAULT_SITES), min_length=1)
    results_wanted: int = Field(default=100, ge=1, le=1000)
    hours_old: int = Field(default=72, ge=1, le=2160)
    country_indeed: str = Field(default="USA", min_length=2, max_length=64)
    attempts: int = Field(
        default=3, ge=1, le=10, description="Attempts per site; retries rotate proxies."
    )
    backoff: float = Field(default=2.0, ge=0, le=60, description="Seconds between attempts.")
    use_proxies: bool = Field(
        default=True, description="Validate and rotate free proxies on retries."
    )
    pool_size: int = Field(default=6, ge=1, le=50)

    @field_validator("sites")
    @classmethod
    def _known_sites(cls, value: list[str]) -> list[str]:
        normalised: list[str] = []
        for raw in value:
            name = raw.strip().lower()
            if name not in SUPPORTED_SITES:
                raise ValueError(
                    f"unsupported site {raw!r}; choose from: {', '.join(SUPPORTED_SITES)}"
                )
            if name not in normalised:
                normalised.append(name)
        return normalised

    def to_query(self) -> SearchQuery:
        return SearchQuery(
            search_term=self.search_term,
            location=self.location,
            results_wanted=self.results_wanted,
            hours_old=self.hours_old,
            country_indeed=self.country_indeed,
        )

    def to_job(self) -> ScrapeJob:
        return ScrapeJob(
            query=self.to_query(),
            sites=tuple(self.sites),
            attempts=self.attempts,
            backoff=self.backoff,
            use_proxies=self.use_proxies,
            pool_size=self.pool_size,
        )


class SiteReport(BaseModel):
    """Outcome for a single job board."""

    site: str
    ok: bool
    jobs: int
    attempts: int
    proxy: str | None = None
    error: str | None = None

    @classmethod
    def from_result(cls, result: SiteResult) -> SiteReport:
        return cls(
            site=result.site,
            ok=result.ok,
            jobs=len(result.jobs),
            attempts=result.attempts,
            proxy=result.proxy,
            error=result.error,
        )


class ScrapeResponse(BaseModel):
    """Body of a successful ``POST /scrape``."""

    count: int
    elapsed_ms: int
    all_failed: bool
    sites: list[SiteReport]
    jobs: list[dict[str, Any]]

    @classmethod
    def from_report(cls, report: ScrapeReport, jobs: list[dict[str, Any]]) -> ScrapeResponse:
        return cls(
            count=len(jobs),
            elapsed_ms=int(report.elapsed_s * 1000),
            all_failed=report.all_failed,
            sites=[SiteReport.from_result(result) for result in report.sites],
            jobs=jobs,
        )
