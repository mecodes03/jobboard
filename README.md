# job_board

Scrapes job boards with the local [JobSpy fork](../jobspy-py) and writes the results to
`{timestamp}_JOBS.csv`.

> The scraper package used to be called `python-jobspy` on PyPI. Do **not** install
> `jobspy` — that name belongs to an unrelated Redis job-control library. The fork is
> distributed as `jobspy-py` but still imports as `jobspy`.

## Setup

```bash
uv sync          # create .venv and install from pyproject.toml + uv.lock
```

`uv sync` expects the fork to exist at `../jobspy-py`. If it isn't there, clone it first:

```bash
git clone git@github.com:mecodes03/JobSpy.git ../jobspy-py
```

## Using the local JobSpy fork

The fork is installed **editable**, so it is the source you are editing:

```toml
[tool.uv.sources]
jobspy-py = { path = "../jobspy-py", editable = true }
```

```bash
uv run python -c "import jobspy; print(jobspy.__file__)"
# /home/mecodes/code/projects/job_board/jobspy-py/jobspy/__init__.py
```

| Change in `jobspy-py` | What to run here |
| --- | --- |
| Python code | nothing — edits are live |
| Dependencies in its `pyproject.toml` | `uv lock` |
| Version number | `uv lock` |
| New console script / entry point | `uv sync --reinstall-package jobspy-py` |

To pin the fork from git instead of a local path (for CI or for other people cloning this
repo), replace the source with:

```bash
uv add "jobspy-py @ git+ssh://git@github.com/mecodes03/JobSpy.git"
# keep it live while developing:
uv add --editable "jobspy-py @ git+ssh://git@github.com/mecodes03/JobSpy.git"
```

## Usage

```bash
uv run job_board                                # all 5 sites, 100 results each
uv run job_board --sites indeed linkedin --results-wanted 50
uv run job_board --search-term "Data Engineer" --location "Austin, TX"
uv run job_board --no-proxies                   # skip the proxy pool (fast, often blocked)
uv run python -m job_board --help               # same as `uv run job_board --help`
```

Every run writes `YYYYMMDD_HHMMSS_JOBS.csv` to `--output-dir` (default: the current
directory). The CSV is ignored by git.

## How failures are handled

- Each site is scraped in its own thread, so a failure never costs you the other sites.
- Each site gets `--attempts` tries (default 3). Attempt 1 goes direct; retries rotate
  through a pool of validated free proxies.
- A proxy that fails is dropped from the pool for the rest of the run, so the next attempt
  always uses a different one.
- `--backoff` (default 2s) grows linearly between attempts.
- Partial results are kept: if a board returns rows *and* an error, the rows are written
  and the failure is logged as a warning.

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | CSV written |
| 1 | No jobs found on any site |
| 2 | Invalid arguments |

## Development

```bash
uv add <pkg>                      # add a runtime dependency
uv add --dev <pkg>                # add a dev dependency
uv remove <pkg>                   # remove one
uv run ruff check src             # lint (after `uv add --dev ruff`)
```
