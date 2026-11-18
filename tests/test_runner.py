"""The shared orchestration layer that CLI, API and Actor all call."""

from __future__ import annotations

import pandas as pd
import pytest

from job_board import runner
from job_board.models import ScrapeJob, ScrapeRequest
from job_board.scraper import SiteResult


class FakePool:
    instances: list[FakePool] = []

    def __init__(self, target_size: int = 6) -> None:
        self.target_size = target_size
        self.refreshed = False
        FakePool.instances.append(self)

    def refresh(self) -> int:
        self.refreshed = True
        return 3


@pytest.fixture(autouse=True)
def _reset() -> None:
    FakePool.instances.clear()


def test_build_pool_is_skipped_without_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ProxyPool", FakePool)

    assert runner.build_pool(ScrapeJob(attempts=1)) is None
    assert runner.build_pool(ScrapeJob(use_proxies=False)) is None
    assert FakePool.instances == []


def test_build_pool_validates_when_retries_can_use_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "ProxyPool", FakePool)

    pool = runner.build_pool(ScrapeJob(attempts=3, pool_size=4))

    assert isinstance(pool, FakePool)
    assert pool.refreshed is True
    assert pool.target_size == 4


def test_run_scrape_combines_and_reports(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_scrape_all(sites, query, pool, *, attempts, backoff):  # type: ignore[no-untyped-def]
        captured.update(
            sites=list(sites), query=query, pool=pool, attempts=attempts, backoff=backoff
        )
        return [
            SiteResult(site="indeed", jobs=pd.DataFrame({"id": [1, 2]}), attempts=1),
            SiteResult(site="linkedin", attempts=2, error="403 Forbidden"),
        ]

    monkeypatch.setattr(runner, "scrape_all", fake_scrape_all)
    monkeypatch.setattr(runner, "ProxyPool", FakePool)

    job = ScrapeRequest(
        sites=["indeed", "linkedin"], attempts=2, backoff=0, use_proxies=False
    ).to_job()
    report = runner.run_scrape(job)

    assert captured["sites"] == ["indeed", "linkedin"]
    assert captured["attempts"] == 2
    assert captured["backoff"] == 0
    assert captured["pool"] is None
    assert report.count == 2
    assert report.all_failed is False
    assert report.elapsed_s >= 0
    assert [result.site for result in report.sites] == ["indeed", "linkedin"]


def test_all_failed_is_flagged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        runner,
        "scrape_all",
        lambda *args, **kwargs: [SiteResult(site="indeed", attempts=1, error="boom")],
    )

    report = runner.run_scrape(ScrapeJob(attempts=1))

    assert report.count == 0
    assert report.all_failed is True
