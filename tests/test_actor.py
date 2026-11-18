"""Apify Actor glue: input mapping and mode detection."""

from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from jobboard import actor, serve
from jobboard.models import ScrapeReport
from jobboard.scraper import DEFAULT_SITES, SiteResult


def test_empty_input_uses_defaults() -> None:
    request = actor.request_from_input(None)
    assert request.search_term == "Software Engineer"
    assert tuple(request.sites) == DEFAULT_SITES


def test_camel_case_input_is_mapped() -> None:
    request = actor.request_from_input(
        {
            "searchTerm": "Data Engineer",
            "location": "Austin, TX",
            "sites": ["indeed", "naukri"],
            "resultsWanted": 25,
            "hoursOld": 48,
            "countryIndeed": "germany",
            "attempts": 2,
            "backoff": 0,
            "useProxies": False,
            "poolSize": 3,
        }
    )

    assert request.search_term == "Data Engineer"
    assert request.location == "Austin, TX"
    assert request.sites == ["indeed", "naukri"]
    assert request.results_wanted == 25
    assert request.hours_old == 48
    assert request.country_indeed == "germany"
    assert request.attempts == 2
    assert request.backoff == 0
    assert request.use_proxies is False
    assert request.pool_size == 3


def test_unknown_input_keys_are_ignored_but_bad_sites_are_not() -> None:
    assert actor.request_from_input({"notAThing": 1}).search_term == "Software Engineer"

    with pytest.raises(ValidationError):
        actor.request_from_input({"sites": ["monster"]})


def test_none_values_fall_back_to_defaults() -> None:
    request = actor.request_from_input({"searchTerm": None, "sites": None})
    assert request.search_term == "Software Engineer"
    assert tuple(request.sites) == DEFAULT_SITES


def test_report_summary_pushed_to_the_key_value_store() -> None:
    jobs = pd.DataFrame({"id": [1, 2], "title": ["a", "b"]})
    report = ScrapeReport(
        jobs=jobs,
        sites=[SiteResult(site="indeed", jobs=jobs, attempts=1)],
        elapsed_s=1.5,
    )

    from jobboard.models import ScrapeResponse

    summary = ScrapeResponse.from_report(report, []).model_dump(exclude={"jobs"})

    assert summary["count"] == 0  # no records passed in
    assert summary["sites"][0]["jobs"] == 2
    assert summary["elapsed_ms"] == 1500


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({}, False),
        ({"APIFY_IS_AT_HOME": "1"}, True),
        ({"ACTOR_RUN_ID": "abc"}, True),
        ({"JOBBOARD_MODE": "api", "ACTOR_RUN_ID": "abc"}, False),
        ({"JOBBOARD_MODE": "actor"}, True),
        ({"APIFY_LOCAL_STORAGE_DIR": "/tmp/store"}, True),
    ],
)
def test_mode_detection(env: dict[str, str], expected: bool, monkeypatch: pytest.MonkeyPatch) -> None:
    for key in ("APIFY_IS_AT_HOME", "ACTOR_RUN_ID", "JOBBOARD_MODE", "APIFY_LOCAL_STORAGE_DIR"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)

    assert serve._is_actor() is expected
