"""Job scraping helpers built on top of python-jobspy."""

__version__ = "0.1.0"

from jobboard.cli import main
from jobboard.scraper import SearchQuery, combine, scrape_all, scrape_site
from jobboard.storage import write_jobs

__all__ = [
    "__version__",
    "main",
    "SearchQuery",
    "combine",
    "scrape_all",
    "scrape_site",
    "write_jobs",
]
