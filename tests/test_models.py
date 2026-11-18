"""Request validation and the mapping to scrape parameters."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from jobboard.models import SUPPORTED_SITES, ScrapeRequest, SiteReport
from jobboard.scraper import DEFAULT_SITES, SiteResult


def test_defaults_match_the_cli() -> None:
    request = ScrapeRequest()
    assert request.search_term == "Software Engineer"
    assert request.location == "San Francisco, CA"
    assert tuple(request.sites) == DEFAULT_SITES


def test_sites_are_normalised_and_deduplicated() -> None:
    request = ScrapeRequest(sites=["Indeed", "LINKEDIN", "indeed"])
    assert request.sites == ["indeed", "linkedin"]


def test_unknown_site_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported site 'monster'"):
        ScrapeRequest(sites=["indeed", "monster"])


def test_google_is_not_offered() -> None:
    # It needs google_search_term, which this request model does not carry.
    assert "google" not in SUPPORTED_SITES
    assert set(DEFAULT_SITES) <= set(SUPPORTED_SITES)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("results_wanted", 0),
        ("results_wanted", 1001),
        ("hours_old", 0),
        ("attempts", 0),
        ("attempts", 11),
        ("backoff", -1),
        ("pool_size", 0),
    ],
)
def test_out_of_range_values_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        ScrapeRequest(**{field: value})  # type: ignore[arg-type]


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ScrapeRequest.model_validate({"sites": ["indeed"], "proxies": "http://x"})


def test_to_job_carries_every_knob() -> None:
    request = ScrapeRequest(
        search_term="Data Engineer",
        location="Austin, TX",
        sites=["linkedin"],
        results_wanted=50,
        hours_old=24,
        attempts=2,
        backoff=0.5,
        use_proxies=False,
        pool_size=3,
    )

    job = request.to_job()

    assert job.query.search_term == "Data Engineer"
    assert job.query.location == "Austin, TX"
    assert job.query.results_wanted == 50
    assert job.sites == ("linkedin",)
    assert job.attempts == 2
    assert job.backoff == 0.5
    assert job.use_proxies is False
    assert job.pool_size == 3


def test_site_report_from_result() -> None:
    import pandas as pd

    result = SiteResult(site="indeed", jobs=pd.DataFrame({"id": [1, 2]}), attempts=2, proxy="http://p:1")
    report = SiteReport.from_result(result)

    assert report.model_dump() == {
        "site": "indeed",
        "ok": True,
        "jobs": 2,
        "attempts": 2,
        "proxy": "http://p:1",
        "error": None,
    }
