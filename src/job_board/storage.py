"""CSV export."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

FILENAME_TEMPLATE = "{timestamp}_JOBS.csv"


def timestamped_path(directory: Path | str = ".", prefix: str = "JOBS") -> Path:
    """Build ``{timestamp}_JOBS.csv`` for the current moment."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(directory) / f"{stamp}_{prefix}.csv"


def write_jobs(jobs: pd.DataFrame, directory: Path | str = ".") -> Path:
    """Write the jobs DataFrame to a timestamped CSV and return its path."""
    path = timestamped_path(directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    jobs.to_csv(path, index=False, encoding="utf-8")
    log.info("wrote %d jobs to %s", len(jobs), path)
    return path
