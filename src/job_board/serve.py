"""Container entrypoint.

Apify runs the image with ``ACTOR_RUN_ID``/``ACTOR_STANDBY_PORT`` set, so the
same Dockerfile has to behave as an Actor there and as a plain web server
everywhere else (Railway, Fly, a laptop).

    JOB_BOARD_MODE=api     always serve the API
    JOB_BOARD_MODE=actor   always run the Actor
    unset                  detect: Apify env vars -> Actor, otherwise API
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger("job_board.serve")


def _is_actor() -> bool:
    mode = os.environ.get("JOB_BOARD_MODE", "").strip().lower()
    if mode == "api":
        return False
    if mode == "actor":
        return True
    return bool(
        os.environ.get("APIFY_IS_AT_HOME")
        or os.environ.get("ACTOR_RUN_ID")
        # `apify run` points the SDK at a local storage directory; treat that as
        # Actor mode too, so local testing exercises the same path as Apify.
        or os.environ.get("APIFY_LOCAL_STORAGE_DIR")
    )


def serve_api() -> int:
    import uvicorn

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "4321"))
    log.info("serving the job_board API on http://%s:%d", host, port)
    uvicorn.run(
        "job_board.api:app",
        host=host,
        port=port,
        log_config=None,  # keep the logging configured below
        access_log=os.environ.get("JOB_BOARD_ACCESS_LOG", "1") != "0",
    )
    return 0


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("JOB_BOARD_LOG_LEVEL", "INFO"),
        format="%(levelname)-7s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    if _is_actor():
        from job_board.actor import run as run_actor

        return run_actor()
    return serve_api()


if __name__ == "__main__":
    raise SystemExit(main())
