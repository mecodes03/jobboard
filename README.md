# jobboard

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
# /home/mecodes/code/projects/jobboard/jobspy-py/jobspy/__init__.py
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
uv run jobboard                                # all 5 sites, 100 results each
uv run jobboard --sites indeed linkedin --results-wanted 50
uv run jobboard --search-term "Data Engineer" --location "Austin, TX"
uv run jobboard --no-proxies                   # skip the proxy pool (fast, often blocked)
uv run python -m jobboard --help               # same as `uv run jobboard --help`
```

Every run writes `YYYYMMDD_HHMMSS_JOBS.csv` to `--output-dir` (default: the current
directory). The CSV is ignored by git.

## HTTP API

The API is FastAPI. Install the extra once:

```bash
uv sync --extra api
uv run jobboard-api                            # http://0.0.0.0:4321, docs at /docs
# or: uv run uvicorn jobboard.api:app --port 4321
```

| Endpoint | What it does |
| --- | --- |
| `GET /health` | Version, JobSpy version, supported boards |
| `GET /sites` | Boards you can pass to `sites` |
| `POST /scrape` | Body of scrape params, returns `{count, elapsed_ms, all_failed, sites[], jobs[]}` |
| `GET /scrape` | Same, with query params (`?sites=indeed&search_term=SRE`) |
| `POST /scrape.csv` | Same body, returns a CSV attachment |

```bash
curl -X POST localhost:4321/scrape \
  -H 'content-type: application/json' \
  -d '{"sites":["indeed"],"search_term":"python developer","location":"Austin, TX",
       "results_wanted":5,"attempts":1,"use_proxies":false}' | jq '.count'

# same thing over the query string; repeat `sites` for several boards
curl 'localhost:4321/scrape?sites=indeed&sites=linkedin&search_term=SRE&results_wanted=5'
```

Request fields mirror the CLI flags (`sites`, `results_wanted`, `hours_old`,
`country_indeed`, `attempts`, `backoff`, `use_proxies`, `pool_size`) plus
`search_term`/`location`. Unknown boards, out-of-range limits and unknown fields are
rejected with `422`.

Response semantics:

| Status | Meaning |
| --- | --- |
| `200` | Scrape ran; inspect `count` and per-board `sites[]` |
| `404` | (`/scrape.csv` only) ran fine, nothing matched |
| `422` | Bad request |
| `502` | Every board failed; body is the same shape as a success |
| `504` | Exceeded `JOBBOARD_TIMEOUT` |

Configuration:

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `4321` | Listen port |
| `JOBBOARD_API_TOKEN` | unset | When set, require `Authorization: Bearer <token>` |
| `JOBBOARD_MAX_CONCURRENCY` | `2` | Scrapes allowed to run at once |
| `JOBBOARD_TIMEOUT` | `600` | Per-request wall clock limit, seconds |

> A scrape is synchronous from the caller's point of view: a five-board, 100-result run
> can take minutes. Raise `JOBBOARD_TIMEOUT` (and your proxy's timeout) rather than
> hammering the endpoint.

## Docker

The image is a single artifact that works both as a web server and as an Apify Actor.
It repoints the `../jobspy-py` path dependency at the git fork and the Tsinghua mirror
at PyPI at build time.

```bash
docker build -t jobboard .
docker run --rm -p 4321:4321 -e JOBBOARD_API_TOKEN=secret jobboard
curl localhost:4321/health
```

## Apify

`.actor/` holds the deployment definition (`usesStandbyMode: true`, input schema,
dataset and key-value-store schemas, and an OpenAPI spec generated from the API).

```bash
npm i -g apify-cli          # once
apify login                 # once
apify push                  # builds the root Dockerfile on Apify
```

The same image behaves differently depending on how it is started, so you get both
contracts without a second build:

- **Regular run** (`apify call`, schedules, Console): reads `INPUT`, scrapes, pushes one
  dataset item per posting, and stores the CSV as `OUTPUT` plus the per-board summary as
  `REPORT` in the key-value store.
- **Standby** (Apify sets `ACTOR_STANDBY_PORT`): serves the API on the platform's port,
  so the endpoints above are reachable at `https://USER--jobboard-scraper.apify.actor`
  with an Apify token.

Test the Actor contract locally without an Apify account:

```bash
export APIFY_LOCAL_STORAGE_DIR=/tmp/actor-store
mkdir -p "$APIFY_LOCAL_STORAGE_DIR/key_value_stores/default"
echo '{"searchTerm":"devops","location":"Austin, TX","sites":["indeed"],
       "resultsWanted":2,"attempts":1,"useProxies":false}' \
  > "$APIFY_LOCAL_STORAGE_DIR/key_value_stores/default/INPUT.json"
uv run --extra apify python -m jobboard.actor
cat "$APIFY_LOCAL_STORAGE_DIR/key_value_stores/default/REPORT"

# Standby mode, same image:
ACTOR_STANDBY_PORT=4321 uv run --extra apify python -m jobboard.actor
```

After changing `src/jobboard/api.py`, regenerate the Actor's OpenAPI spec:

```bash
uv run python scripts/export_openapi.py
```

## Tests

```bash
uv sync --extra api --extra apify          # tests import fastapi + apify
uv run pytest
uv run pyright
```

The suite is offline: scraping is monkeypatched, so it runs in ~2s and never hits a job
board. Coverage is the JSON/CSV normalisation, request validation, retry/pool wiring, the
HTTP contract (including 401/502/504 and the CSV download) and the Actor input mapping.

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
