"""JSON/CSV conversion must survive everything pandas and JobSpy can produce."""

from __future__ import annotations

import json
from datetime import date, datetime

import numpy as np
import pandas as pd

from job_board.export import to_csv_bytes, to_records


def test_empty_frame_gives_no_records() -> None:
    assert to_records(pd.DataFrame()) == []


def test_normalises_the_awkward_values() -> None:
    df = pd.DataFrame(
        {
            "id": [1, 2],
            "title": ["Engineer", None],
            "min_amount": [np.float64(120000.0), np.nan],
            "is_remote": [np.bool_(True), np.bool_(False)],
            "date_posted": [pd.Timestamp("2026-11-15"), pd.NaT],
            "emails": [["a@example.com"], None],
            "meta": [{"source": "indeed"}, None],
        }
    )

    records = to_records(df)

    assert records[0] == {
        "id": 1,
        "title": "Engineer",
        "min_amount": 120000.0,
        "is_remote": True,
        "date_posted": "2026-11-15T00:00:00",
        "emails": ["a@example.com"],
        "meta": {"source": "indeed"},
    }
    assert records[1] == {
        "id": 2,
        "title": None,
        "min_amount": None,
        "is_remote": False,
        "date_posted": None,
        "emails": None,
        "meta": None,
    }
    # The whole point: this must not raise.
    json.dumps(records)


def test_infinite_floats_are_nulled() -> None:
    df = pd.DataFrame({"salary": [float("inf"), float("-inf")]})
    assert [row["salary"] for row in to_records(df)] == [None, None]


def test_datetime_and_date_become_iso_strings() -> None:
    df = pd.DataFrame(
        {"a": [datetime(2026, 11, 17, 12, 0)], "b": [date(2026, 11, 17)]}
    )
    row = to_records(df)[0]
    assert row["a"] == "2026-11-17T12:00:00"
    assert row["b"] == "2026-11-17"


def test_csv_bytes_are_utf8_with_header() -> None:
    df = pd.DataFrame({"title": ["Développeur"], "id": [1]})
    raw = to_csv_bytes(df)
    assert isinstance(raw, bytes)
    assert raw.decode("utf-8").splitlines() == ["title,id", "Développeur,1"]
