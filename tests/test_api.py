"""HTTP contract tests. Nothing here touches the network."""

from __future__ import annotations

import time

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from job_board import api
from job_board.models import ScrapeReport
from job_board.scraper import SiteResult

SAMPLE = pd.DataFrame(
    {
        "id": [1, 2],
        "site": ["indeed", "linkedin"],
        "title": ["Backend Engineer", "Data Engineer"],
        "min_amount": [120000.0, None],
    }
)


def _report(rows: int = 2) -> ScrapeReport:
    jobs = SAMPLE.head(rows)
    return ScrapeReport(
        jobs=jobs,
        sites=[
            SiteResult(site="indeed", jobs=jobs.iloc[:1], attempts=1),
            SiteResult(site="linkedin", attempts=2, error="403 Forbidden"),
        ],
        elapsed_s=0.25,
    )


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(api, "run_scrape", lambda job: _report())
    return TestClient(api.app)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JOB_BOARD_API_TOKEN", raising=False)
    monkeypatch.delenv("APIFY_IS_AT_HOME", raising=False)


def test_health(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert "indeed" in body["sites"]
    assert "google" not in body["sites"]


def test_sites(client: TestClient) -> None:
    body = client.get("/sites").json()
    assert "indeed" in body["supported"]
    assert body["default"][0] == "indeed"


def test_scrape_returns_rows_and_per_site_report(client: TestClient) -> None:
    response = client.post("/scrape", json={"sites": ["indeed", "linkedin"]})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    assert body["all_failed"] is False
    assert body["elapsed_ms"] == 250
    assert [row["title"] for row in body["jobs"]] == ["Backend Engineer", "Data Engineer"]
    assert [site["ok"] for site in body["sites"]] == [True, False]
    assert body["sites"][1]["error"] == "403 Forbidden"


def test_scrape_accepts_query_string_for_curl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, object] = {}

    def capture(job):  # type: ignore[no-untyped-def]
        seen.update(sites=job.sites, term=job.query.search_term, wanted=job.query.results_wanted)
        return _report()

    monkeypatch.setattr(api, "run_scrape", capture)
    client = TestClient(api.app)

    response = client.get(
        "/scrape",
        params={"sites": ["indeed", "linkedin"], "search_term": "SRE", "results_wanted": 5},
    )

    assert response.status_code == 200
    # The query string must actually reach the scrape; a 200 alone proves nothing.
    assert seen == {"sites": ("indeed", "linkedin"), "term": "SRE", "wanted": 5}


def test_query_string_rejects_unknown_site(client: TestClient) -> None:
    assert client.get("/scrape", params={"sites": "monster"}).status_code == 422


def test_unknown_site_is_a_422(client: TestClient) -> None:
    response = client.post("/scrape", json={"sites": ["monster"]})

    assert response.status_code == 422
    assert "unsupported site" in response.text


def test_bad_limit_is_a_422(client: TestClient) -> None:
    assert client.post("/scrape", json={"results_wanted": 0}).status_code == 422


def test_every_site_failing_is_a_502_with_the_same_body_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = ScrapeReport(
        jobs=pd.DataFrame(),
        sites=[SiteResult(site="indeed", attempts=3, error="403 Forbidden")],
        elapsed_s=6.0,
    )
    monkeypatch.setattr(api, "run_scrape", lambda job: failed)

    response = TestClient(api.app).post("/scrape", json={"sites": ["indeed"]})

    assert response.status_code == 502
    body = response.json()
    assert body["all_failed"] is True
    assert body["count"] == 0
    assert body["sites"][0]["error"] == "403 Forbidden"


def test_timeout_is_a_504(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(job):  # type: ignore[no-untyped-def]
        time.sleep(0.3)
        return _report()

    monkeypatch.setattr(api, "run_scrape", slow)
    monkeypatch.setattr(api, "_timeout_s", lambda: 0.01)

    response = TestClient(api.app).post("/scrape", json={"sites": ["indeed"]})

    assert response.status_code == 504


def test_csv_download(client: TestClient) -> None:
    response = client.post("/scrape.csv", json={"sites": ["indeed"]})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.headers["content-disposition"].startswith("attachment; filename=")
    assert response.headers["x-job-count"] == "2"
    header, *rows = response.text.splitlines()
    assert header.startswith("id,site,title")
    assert len(rows) == 2


def test_csv_with_no_matches_is_a_404(monkeypatch: pytest.MonkeyPatch) -> None:
    empty_ok = ScrapeReport(
        jobs=pd.DataFrame(),
        sites=[SiteResult(site="indeed", jobs=pd.DataFrame(), attempts=1)],
        elapsed_s=1.0,
    )
    monkeypatch.setattr(api, "run_scrape", lambda job: empty_ok)

    assert TestClient(api.app).post("/scrape.csv", json={"sites": ["indeed"]}).status_code == 404


def test_token_is_required_when_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JOB_BOARD_API_TOKEN", "s3cret")

    assert client.post("/scrape", json={}).status_code == 401
    assert client.post("/scrape", json={}, headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.post("/scrape", json={}, headers={"Authorization": "Bearer s3cret"}).status_code == 200
    # The docs stay public so the service is discoverable.
    assert client.get("/health").status_code == 200


def test_apify_defers_authentication_to_the_platform(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("JOB_BOARD_API_TOKEN", "s3cret")
    monkeypatch.setenv("APIFY_IS_AT_HOME", "1")

    assert client.post("/scrape", json={}).status_code == 200
