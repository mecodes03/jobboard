"""DataFrame -> JSON/CSV conversion.

JobSpy returns pandas frames full of values that ``json.dumps`` refuses:
``NaN``, ``NaT``, ``numpy.int64``, ``numpy.bool_``, ``pandas.Timestamp`` and
occasionally lists (``emails``). Everything that leaves this package - HTTP
responses and Apify datasets alike - goes through :func:`to_records`, so the
normalisation lives in exactly one place.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def _jsonable(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    # numpy scalars (int64, bool_, float64 aliases) expose .item().
    item = getattr(value, "item", None)
    if callable(item) and not isinstance(value, (list, dict)):
        try:
            return _jsonable(item())
        except (AttributeError, TypeError, ValueError):
            pass
    isoformat = getattr(value, "isoformat", None)
    if callable(isoformat):
        try:
            return isoformat()
        except (AttributeError, TypeError, ValueError):
            pass
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, (bool, np.bool_)) and missing:
        return None
    return str(value)


def to_records(jobs: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert a jobs frame into JSON-safe records (empty frame -> empty list)."""
    if jobs is None or jobs.empty:
        return []
    return [
        {str(column): _jsonable(value) for column, value in row.items()}
        for row in jobs.to_dict(orient="records")
    ]


def to_csv_bytes(jobs: pd.DataFrame) -> bytes:
    """Render the jobs frame as UTF-8 CSV, header included even when empty."""
    return jobs.to_csv(index=False, encoding="utf-8").encode("utf-8")
