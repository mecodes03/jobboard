# WORKING.md — how this project works

This document explains the architecture of `jobboard`: what each file does, how the
pieces connect, and what happens on a real scrape. It assumes you're new to Python,
so concepts are explained the first time they matter.

---

## 1. What this project does

`jobboard` scrapes job postings from public job boards (Indeed, LinkedIn,
Glassdoor, ZipRecruiter, Naukri) and saves them to a timestamped CSV file:

```
20261117_143210_JOBS.csv
└── timestamp: 2026-11-17, 14:32:10
```

It can be triggered **three different ways**, and all three share the exact same
scraping engine:

1. **CLI** — run it in your terminal: `uv run jobboard`
2. **HTTP API** — a web server you can `curl`: `uv run jobboard-api`
3. **Apify Actor** — a cloud-scraping platform integration: deployed via Docker

The actual scraping is done by an external library called **JobSpy** (a fork living
in `../jobspy-py`). This project wraps it, adds retries + proxies, and exposes it
through those three front doors.

---

## 2. The big picture

```
        ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
        │   cli.py    │   │   api.py    │   │  actor.py   │        ← "front doors"
        │  terminal   │   │  FastAPI    │   │  Apify      │           (parse input,
        └──────┬──────┘   └──────┬──────┘   └──────┬──────┘            format output)
               │                 │                 │
               │            validate & translate   │
               └─────────────┬───┴─────────────────┘
                             ▼
                         models.py                          ← shared data shapes
                             │
                             ▼
                         runner.py                          ← run_scrape(): one scrape,
                             │                               start to finish
              ┌──────────────┴──────────────┐
              ▼                             ▼
          proxies.py                   scraper.py           ← engine: 1 thread per
          (validated proxy pool)       (retry per site)        site, rotating proxies
                                            │
                                            ▼
                                  jobspy  (external library in ../jobspy-py)
```

And on the way **out**, each front door formats the same result its own way:

```
   cli.py   → storage.py  → a CSV file on disk
   api.py   → export.py   → JSON / CSV bytes over HTTP
   actor.py → export.py   → rows in the Apify dataset + OUTPUT.csv + REPORT
```

**The design rule of this codebase:** the front doors only *parse input* and
*format output*. Everything in between — validation, orchestration, scraping,
retries — lives in shared modules, so fixing a bug once fixes it everywhere.

---

## 3. Python concepts used here (quick primer)

You'll meet these repeatedly. Each maps to real code in this repo:

| Concept | What it means | Where you see it |
|---|---|---|
| **module** | Any single `.py` file. `from jobboard.cli import main` = "from the `cli.py` file inside the `jobboard` folder, grab the `main` function". | everywhere |
| **package** | A folder of modules with an `__init__.py`. `jobboard` is the package; importing it runs `__init__.py` first. Project, commands and imports all share the single spelling `jobboard`. | `src/jobboard/` |
| **src layout** | Code lives in `src/`, not at the repo root. When you `uv sync`, the package gets *installed* into `.venv`, which is why `import jobboard` works from anywhere. | `pyproject.toml` |
| **entry point** | A command that gets created in `.venv/bin/` when the package is installed. Defined in `[project.scripts]`. `jobboard = "jobboard:main"` means: the terminal command `jobboard` calls the function `main()` in the `jobboard` package. | `pyproject.toml` |
| **`__main__.py`** | A special file that makes `python -m jobboard` work. Python looks for it when you run a package with `-m`. | `src/jobboard/__main__.py` |
| **dataclass** | A class whose job is mostly *holding data* — the `@dataclass` decorator auto-generates the constructor. `frozen=True` = can't be modified after creation. | `models.py`, `scraper.py` |
| **Pydantic model** | A class that *validates* data at runtime. If the input is wrong (bad site name, out-of-range number), it raises an error with a helpful message. Used at every boundary where outside data enters. | `models.py` |
| **pandas DataFrame** | A spreadsheet in memory: rows and named columns. JobSpy returns scraped jobs as one. `df.empty`, `df.to_csv()`, `pd.concat()` are operations on that spreadsheet. | `scraper.py`, `storage.py` |
| **ThreadPoolExecutor** | Runs the same function many times *in parallel* (one thread per site). Threads are how Python does several network downloads at once. | `scraper.py`, `proxies.py` |
| **`async` / `await`** | Cooperative multitasking: one thread juggles many waiting requests. The API server uses it; blocking work (the scrape) is pushed to a worker thread with `asyncio.to_thread()`. | `api.py` |
| **decorator** | `@something` above a function wraps/modifies it. `@app.get("/health")` registers the function below it as an HTTP endpoint. | `api.py` |
| **`uv`** | The package manager this project uses. `uv sync` creates `.venv` and installs dependencies; `uv run X` runs command `X` inside that virtual environment. | everywhere |
| **editable install** | The JobSpy fork at `../jobspy-py` is installed "editable", meaning Python imports it *directly from that folder* — edit the fork's code and the changes are live here with no reinstall. | `pyproject.toml` |
| **`__pycache__/`** | Auto-generated compiled bytecode. It's a cache — safe to ignore and delete, and it's git-ignored. | `src/jobboard/__pycache__/` |

---

## 4. File map

```
src/jobboard/
├── __init__.py      # package front page: re-exports the public functions
├── __main__.py      # makes `python -m jobboard` work (delegates to cli.main)
├── cli.py           # front door 1: terminal flags → ScrapeJob → CSV file
├── api.py           # front door 2: HTTP endpoints (FastAPI app)
├── actor.py         # front door 3: Apify Actor (batch job or standby API server)
├── serve.py         # container launcher: decides Actor vs API at startup
├── models.py        # shared data shapes: ScrapeJob, ScrapeReport, ScrapeRequest
├── runner.py        # run_scrape(): the one function all three doors call
├── scraper.py       # scrape_all / scrape_site / combine: threads + retries
├── proxies.py       # ProxyPool: download, test, rotate, discard free proxies
├── export.py        # DataFrame → JSON-safe records / CSV bytes
└── storage.py       # DataFrame → timestamped CSV file on disk
```

Supporting files:

```
pyproject.toml        # package metadata, dependencies, entry points, tool config
uv.lock               # exact pinned dependency versions (auto-generated, committed)
Dockerfile            # one image that works as API server AND Apify Actor
.actor/               # Apify deployment definition (input schema, OpenAPI spec…)
scripts/export_openapi.py  # regenerates .actor/openapi.json from the FastAPI app
tests/                # offline test suite (network calls are faked)
```

---

## 5. The shared contract: `models.py`

This is the hinge of the whole project. It defines the data objects that flow
through the pipeline, so the three front doors can't drift apart.

Three objects, in the order they're created:

### `ScrapeRequest` — *external, validated* (Pydantic)
What the outside world sends: an HTTP body, or an Apify Actor's `INPUT`. Pydantic
checks every field (a bad site name or `results_wanted=0` is rejected here, before
any scraping starts). Its `to_job()` method converts it into a `ScrapeJob`.

### `ScrapeJob` — *internal, frozen* (dataclass)
The resolved scrape settings handed to `runner.run_scrape()`. Plain Python object,
no validation needed because it was already validated.

### `ScrapeReport` — *internal result* (dataclass)
What `run_scrape()` returns: the merged `jobs` DataFrame, a `SiteResult` per board
(jobs found, attempts used, proxy, error), total elapsed time, plus helper
properties `count` and `all_failed`.

There's also `ScrapeResponse` (Pydantic) — the JSON body the API returns, built
from a `ScrapeReport` via `ScrapeResponse.from_report()`.

```
outside world          internal pipeline                 back out
─────────────          ─────────────────                 ────────
JSON / flags  ──►  ScrapeRequest ──► ScrapeJob ──► ScrapeReport ──► JSON/CSV/file
  (validated by pydantic)    (plain dataclass)
```

---

## 6. The engine: how a scrape actually runs

Everything funnels into **one function**: `runner.run_scrape(job: ScrapeJob) → ScrapeReport`.
Here's what happens inside, step by step.

### Step 1 — build the proxy pool (`runner.build_pool`)

- Skipped entirely if `use_proxies=False` or `attempts < 2` (a retry is the only
  thing that would use a proxy).
- Otherwise creates a `ProxyPool` and calls `refresh()`, which:
  1. downloads a raw list of free HTTP proxies from proxyscrape.com,
  2. tests up to 120 of them **in parallel** (30 threads) by fetching `httpbin.org/ip` through each,
  3. keeps the first 6 that answer (the `pool_size`), drops the rest.
- If zero survive, it logs a warning and returns `None` — retries then go direct.

### Step 2 — scrape every site concurrently (`scraper.scrape_all`)

A `ThreadPoolExecutor` spawns **one thread per site**. Each thread calls
`scrape_site` for a single board. A site that hangs or crashes never blocks or
breaks the others.

> **Why one site per jobspy call?** JobSpy can scrape all five sites in one call,
> but then a single failure loses the whole batch and you can't retry just one
> board. Calling it once per site makes per-site retrying possible.

### Step 3 — scrape one site with retries (`scraper.scrape_site`)

The retry loop, per site:

1. **Attempt 1 goes direct** (no proxy) — it's the fastest path and often works.
2. On failure: the proxy used (if any) is marked bad and removed from the pool,
   the thread sleeps `backoff × attempt` seconds (so 2s, 4s, 6s…), then **attempt 2
   rotates to a different proxy** from the pool (`pool.next(skip=already_tried)`).
3. `scrape_site` calls `jobspy.scrape_jobs(site_name=[site], …)` via `_scrape_once`,
   getting a DataFrame back.

Judgment calls the code makes about success and failure:

- JobSpy reports per-site errors in `df.attrs["errors"]` *while still returning an
  (possibly empty) DataFrame* — so `_failure()` checks the recorded reason
  **before** checking emptiness, or the real cause (a 403, a dead proxy) is lost.
- **Partial results are kept.** If a board returns some rows *and* an error (it
  got blocked halfway through pagination), the rows are kept and the error is
  dropped — better 40 good jobs than a retry from zero.
- Only an exception or "error and zero rows" counts as a real failure.

### Step 4 — merge everything (`scraper.combine`)

All successful per-site DataFrames are concatenated into one, then:

- **de-duplicated** on the `id` column (unique per posting per site), falling back
  to `site + title + company + location` if `id` is missing,
- **sorted** by site, then newest-posted first (if sorting fails on weird data,
  it keeps scrape order instead of crashing).

### Step 5 — return a `ScrapeReport`

`run_scrape()` bundles the merged DataFrame + per-site results + elapsed time
and returns it. It has *no idea* which front door called it.

---

## 7. The front doors

### 7a. CLI — `cli.py`

Entry: the `jobboard` command (from `pyproject.toml`) or `python -m jobboard`.

```
uv run jobboard --sites indeed linkedin --results-wanted 50 --search-term "SRE"
```

`main()` does:

1. `argparse` parses the flags (`--sites`, `--results-wanted`, `--attempts`,
   `--backoff`, `--no-proxies`, `--pool-size`, `--output-dir`, `-v`…).
2. Builds a `SearchQuery` (what to search) + `ScrapeJob` (search + sites + retry settings).
3. Calls `run_scrape(job)`.
4. Logs a per-site summary (`indeed    87 jobs (1 attempt)` / `linkedin  FAILED …`).
5. Empty result → exit code `1`. Bad arguments → `2`. CSV written → `0`.

Output goes through `storage.write_jobs()` → `{timestamp}_JOBS.csv`.

Detail worth knowing: with default logging, a **filter drops all log records from
the `jobspy` library** (it's extremely chatty about blocked requests). Pass `-v`
to see everything.

### 7b. HTTP API — `api.py`

Entry: the `jobboard-api` command, or `uvicorn jobboard.api:app`.

| Endpoint | Method | Does |
|---|---|---|
| `/health` | GET | version info + supported boards (used as Docker health check) |
| `/sites` | GET | which boards you may pass |
| `/scrape` | POST | body = scrape params → JSON with `{count, elapsed_ms, all_failed, sites[], jobs[]}` |
| `/scrape` | GET | same via query string (`?sites=indeed&sites=linkedin`) |
| `/scrape.csv` | POST | same scrape → downloadable CSV attachment |

How it works inside:

- `@app.post("/scrape")` registers the function as an endpoint; FastAPI
  **validates the JSON body against `ScrapeRequest`** automatically — bad input
  becomes a `422` with zero custom code.
- `require_auth` is a *dependency*: if `JOBBOARD_API_TOKEN` is set, requests must
  carry `Authorization: Bearer <token>` or get `401`. It's skipped when the token
  is unset, and on Apify (the platform authenticates callers itself).
- The scrape is **blocking and slow**, so it runs on a worker thread
  (`asyncio.to_thread`) while the server stays responsive. Two guards wrap it:
  - a `Semaphore` limits concurrent scrapes to `JOBBOARD_MAX_CONCURRENCY` (default 2),
  - `asyncio.wait_for` enforces `JOBBOARD_TIMEOUT` seconds (default 600) → `504` if exceeded.
- Status codes: `200` ran (check `count`), `502` every site failed (body still has
  the same shape, so clients parse one thing), `404` (`/scrape.csv` only) ran fine
  but nothing matched, `422` bad request.

`serve.py` is the **container entrypoint**: at startup it checks environment
variables — `JOBBOARD_MODE=api/actor`, or Apify's `ACTOR_RUN_ID` /
`ACTOR_STANDBY_PORT` / `APIFY_LOCAL_STORAGE_DIR` — and either launches uvicorn
with the API (default host `0.0.0.0`, port `PORT` or `4321`) or runs the Actor.

### 7c. Apify Actor — `actor.py`

Apify is a cloud platform for running scrapers. The same Docker image serves two
contracts depending on how the platform starts it:

**Standby mode** (`ACTOR_STANDBY_PORT` is set): the Actor stays alive and simply
serves the *same FastAPI app* on the port Apify provides. The endpoints above are
then reachable through Apify's container URL. One codebase, two products.

**Regular run** (anything else): the classic batch job —

1. reads `INPUT` (a JSON the platform gives us),
2. `request_from_input()` maps Apify's **camelCase** keys (`searchTerm`,
   `resultsWanted`…) onto the shared **snake_case** `ScrapeRequest` — which is then
   validated by the exact same Pydantic model the API uses,
3. runs `run_scrape()` on a thread,
4. pushes each job as a row into the **dataset** (Apify's result table),
5. stores the CSV as `OUTPUT` and a JSON summary (without the rows) as `REPORT`
   in the **key-value store** (Apify's file storage).

The `.actor/` folder tells the Apify platform how to deploy and use the Actor:
`actor.json` (config, standby mode enabled), `input_schema.json` (the form the
Console shows users — camelCase, matching `_INPUT_FIELDS` in `actor.py`), dataset
and KV-store schemas, and `openapi.json`.

`scripts/export_openapi.py` keeps that last file honest: FastAPI generates an API
description from the code, and this script dumps it into `.actor/openapi.json`.
Run it after changing `api.py`, because Apify renders the spec at build time.

---

## 8. Helper modules

### `proxies.py` — `ProxyPool`

Free proxies die constantly, so the strategy is *small and fresh, not big and stale*:

- `fetch_candidates()` — downloads the raw list from ProxyScrape.
- `test_proxy()` — asks `httpbin.org/ip` through the proxy; returns the URL if it answered.
- `refresh()` — tests candidates with 30 threads, stops as soon as `target_size` pass.
- `next(skip=…)` — round-robin hand-out, skipping proxies this site already tried.
- `mark_bad()` — removes a failed proxy immediately, so it's never handed out again.

A `threading.Lock` protects the internal list because **all site threads share one
pool** and modify it concurrently.

### `export.py` — DataFrame → safe data

Pandas frames are full of values that plain JSON *cannot* represent: `NaN`, `NaT`,
numpy integers, pandas timestamps, booleans-as-numpy-objects, even lists (emails).
`to_records()` walks every cell and normalizes it to something JSON-safe
(`NaN → null`, timestamps → ISO strings, numpy scalars → Python scalars).

**Everything that leaves the package as data** — API JSON responses and Apify
dataset rows — goes through this one function, so the conversion bugs live in
exactly one place. `to_csv_bytes()` renders the same frame as CSV for downloads.

### `storage.py` — CSV file writing

`write_jobs(frame, directory)` builds a `{YYYYMMDD_HHMMSS}_JOBS.csv` name, creates
the directory if needed, writes UTF-8 CSV, returns the path. Used by the CLI (and
its filename generator by the API's CSV download header).

---

## 9. The external dependency: the JobSpy fork

`jobspy` does the actual HTTP scraping of each board. This project installs **a
fork** that lives in a sibling folder, `../jobspy-py`, as an *editable* dependency:

```toml
# pyproject.toml
[tool.uv.sources]
jobspy-py = { path = "../jobspy-py", editable = true }
```

Because it's editable, **the fork's folder is the library** — edit
`../jobspy-py/jobspy/…` and the change is live here on the next `uv run`, no
reinstall. (You *do* need `uv lock` if its dependencies or version change.)

Everything else that references it adapts at build time:

- **Docker**: the build rewrites that path into a git URL, since `../jobspy-py`
  doesn't exist inside a container.

---

## 10. Packaging: `pyproject.toml` and `uv`

`pyproject.toml` is the project's ID card and instruction manual. The sections used:

| Section | Meaning |
|---|---|
| `[project]` | name, version, required Python (≥3.14), runtime deps (`jobspy-py`, `pandas`, `requests`) |
| `[project.scripts]` | terminal commands → functions: `jobboard`, `jobboard-api`, `jobboard-actor` |
| `[project.optional-dependencies]` | **extras**: `api` (fastapi, uvicorn), `apify` (apify SDK). Extras keep heavy deps off a plain CLI install — `uv sync --extra api` adds them. |
| `[dependency-groups]` | `dev` tools (pytest, httpx, pyright…) that never ship to production |
| `[tool.uv.sources]` | the editable path to the JobSpy fork |
| `[tool.pytest.ini_options]` | test discovery config |

`uv` commands you'll actually use:

```bash
uv sync                        # create/update .venv from pyproject.toml + uv.lock
uv sync --extra api --extra apify   # with everything the tests need
uv run <command>               # run a command inside .venv
uv run pytest                  # run the tests
uv add <pkg> / uv remove <pkg> # add/remove a dependency (updates the lock file)
uv run pyright                 # type checking
```

`.venv/` is the **virtual environment**: an isolated folder where this project's
Python and dependencies live, so they can't conflict with other projects or your
system Python. `uv run` activates it for you — you never need to touch it directly.

---

## 11. Docker & deployment: one image, two modes

The `Dockerfile` builds a single image that works everywhere:

1. Base image: `apify/actor-python:3.14` (Apify-compatible Python).
2. Installs `uv`, then **rewrites `pyproject.toml` for the container**: the
   Tsinghua PyPI mirror → pypi.org, and the `../jobspy-py` path → the git fork URL.
   (Neither a sibling folder nor a China-only mirror exists inside a build.)
3. `uv sync` installs dependencies, then source is copied in last — so everyday
   code edits rebuild fast (dependency layers stay cached).
4. `HEALTHCHECK` pokes `/health` (only meaningful in API mode; Apify ignores it).
5. `CMD python -m jobboard.serve` → `serve.py` **decides at runtime**:
   Apify env vars present → Actor mode; absent → API server on `$PORT`.

So the same image runs on your laptop (API), on Railway/Fly (API), and on Apify
(Actor batch run or Standby API) — no second build.

---

## 12. Tests

```bash
uv sync --extra api --extra apify   # tests import fastapi + apify
uv run pytest
```

The suite is **fully offline and fast (~2s)**: the scraping calls are monkeypatched
(replaced with fakes at test time), so nothing ever hits a real job board. One
test file per layer: `test_models.py` (validation), `test_runner.py`
(orchestration), `test_export.py` (normalization), `test_api.py` (HTTP contract,
including auth/502/504/CSV), `test_actor.py` (input mapping).

This is the payoff of the layered design: because all front doors funnel through
`run_scrape`, testing that one path covers all three.

---

## 13. Life of a request — full walkthrough

`curl -X POST localhost:4321/scrape -d '{"sites":["indeed"],"search_term":"python developer","location":"Austin, TX","results_wanted":5,"attempts":3,"use_proxies":false}'`

1. **uvicorn** (started by `jobboard-api`) receives the request on its event loop.
2. FastAPI matches `POST /scrape` → `scrape()` and **validates the body against
   `ScrapeRequest`**. Unknown field? Bad site? → `422`, no scrape code touched.
3. The `require_auth` dependency checks the bearer token (if configured).
4. `_report()` acquires the concurrency semaphore, then runs
   `run_scrape(request.to_job())` **on a worker thread**, with a 600s deadline.
5. Inside the worker thread:
   - `build_pool` → skipped (`use_proxies: false`),
   - `scrape_all(["indeed"])` → one thread runs `scrape_site("indeed", …)`,
   - attempt 1 direct → `jobspy.scrape_jobs(site_name=["indeed"], …)` → DataFrame,
   - say it 403s: `_failure` reads `df.attrs["errors"]`, sleep 2s, attempt 2 (also
     direct — no pool) → this time 5 rows come back → success,
   - `combine` de-dupes and sorts → `ScrapeReport`.
6. Back in the API: `to_records()` normalizes the DataFrame to JSON-safe dicts,
   `ScrapeResponse.from_report()` builds the body, and it's returned as `200`:

```json
{
  "count": 5,
  "elapsed_ms": 4210,
  "all_failed": false,
  "sites": [{"site": "indeed", "ok": true, "jobs": 5, "attempts": 2, "proxy": null}],
  "jobs": [{"title": "Python Developer", "company": "…", "…": "…"}]
}
```

The CLI and Actor walks are the same from step 5 onward — only steps 1–4 and the
output formatting differ.

---

## 14. Failure-handling rules (summary)

- Each site is scraped **in its own thread** — one board failing never costs the others.
- Each site gets `--attempts` tries; attempt 1 direct, later attempts rotate
  through validated free proxies, and a failed proxy is dropped from the pool.
- Backoff between attempts grows linearly (`backoff × attempt`).
- **Partial results are kept** (rows + an error beats no rows).
- All-failed is reported honestly, not hidden: the API returns `502` (same body
  shape as success), the CLI logs the per-site errors, the Actor writes the
  summary to `REPORT`.

---

## 15. "Where do I change…?" cheat sheet

| You want to… | Touch |
|---|---|
| Change default search term / location / limits for **everyone** | `scraper.py` (`SearchQuery`, `DEFAULT_SITES`) + `models.py` (`ScrapeRequest` defaults) + `cli.py` (argparse defaults) |
| Add/remove a request field (CLI + API + Actor all at once) | `models.py` (`ScrapeRequest`), then `cli.py` (flag), `actor.py` (`_INPUT_FIELDS` + `.actor/input_schema.json`) |
| Change retry/proxy behavior | `scraper.py` (`scrape_site`), `proxies.py` |
| Change CSV filename/layout | `storage.py` |
| Add an HTTP endpoint | `api.py`, then `uv run python scripts/export_openapi.py` to refresh `.actor/openapi.json` |
| Change how the container starts up | `serve.py`, `Dockerfile` |
| Change Actor input form | `.actor/input_schema.json` + `_INPUT_FIELDS` in `actor.py` |
| Change what JSON looks like | `export.py` / `models.py` (`ScrapeResponse`) |
| Fix a scraping bug **inside JobSpy itself** | the fork: `../jobspy-py/` — changes are live immediately (editable install) |

Add tests in `tests/` for whatever you change — the existing fakes/monkeypatching
pattern makes new cases cheap.
