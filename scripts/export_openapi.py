"""Regenerate .actor/openapi.json from the FastAPI app.

Apify validates this file at build time and renders it as the Actor's **Server**
tab, so it has to be kept in sync with the endpoints. Run it after changing
job_board.api:

    uv run python scripts/export_openapi.py
"""

from __future__ import annotations

import json
from pathlib import Path

from job_board.api import app

TARGET = Path(__file__).resolve().parents[1] / ".actor" / "openapi.json"


def main() -> None:
    spec = app.openapi()
    TARGET.write_text(json.dumps(spec, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    paths = ", ".join(sorted(spec["paths"]))
    print(f"wrote {TARGET.relative_to(TARGET.parents[1])} ({len(spec['paths'])} paths: {paths})")


if __name__ == "__main__":
    main()
