"""Job scraping helpers built on top of python-jobspy."""

__version__ = "0.1.0"

from job_board.cli import main
from job_board.scraper import SearchQuery, combine, scrape_all, scrape_site
from job_board.storage import write_jobs

__all__ = [
    "__version__",
    "main",
    "SearchQuery",
    "combine",
    "scrape_all",
    "scrape_site",
    "write_jobs",
]
