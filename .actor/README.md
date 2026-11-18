# Job Board Scraper

Scrapes job postings from Indeed, LinkedIn, Glassdoor, ZipRecruiter, Naukri and seven
more boards in a single run, using the [JobSpy](https://github.com/mecodes03/JobSpy) fork.

Each board is fetched in its own thread and retried independently, so a board that
blocks you costs you that board only — never the whole run. Retries rotate through a
small pool of freshly validated free proxies, and a proxy that fails is dropped for the
rest of the run.

## Two ways to use it

**As a batch Actor.** Run it (Console, `apify call`, a schedule) with the input below.
Every posting lands in the default dataset, and the same rows are saved as
`OUTPUT.csv` in the key-value store. `REPORT` holds the per-board summary.

**As a REST API.** The Actor runs in [Standby mode](https://docs.apify.com/platform/actors/development/programming-interface/standby),
so the same container serves the API. Hit the Actor's Standby URL with your Apify token:

```bash
curl "https://USER--jobboard-scraper.apify.actor/scrape?sites=indeed&search_term=Data%20Engineer&results_wanted=25" \
  -H "Authorization: Bearer $APIFY_TOKEN"
```

Endpoints: `GET /health`, `GET /sites`, `GET /scrape`, `POST /scrape`, `POST /scrape.csv`,
plus interactive docs at `/docs`.

## Output

One dataset item per posting with the full JobSpy schema (`title`, `company`, `location`,
`min_amount`/`max_amount`, `currency`, `is_remote`, `job_type`, `date_posted`, `job_url`,
`description`, ...), de-duplicated across boards by `id`.

## Notes

- Full five-board runs take tens of seconds to a few minutes depending on how many boards
  block the request. Raise the run timeout rather than lowering `attempts` if you see 403s.
- Boards occasionally return more rows than `resultsWanted`; that is upstream behaviour.
- Board markup changes regularly. When a board starts returning nothing, check `REPORT`
  for the error before assuming the input is wrong.
