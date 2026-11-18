# syntax=docker/dockerfile:1

# One image, two deployment targets:
#   * Apify Actor  - the platform sets ACTOR_RUN_ID/ACTOR_STANDBY_PORT, so
#     `job_board.serve` runs the Actor (batch run or Standby API).
#   * Any PaaS     - without those variables it serves the FastAPI app on $PORT.
FROM apify/actor-python:3.14

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    PYTHONUNBUFFERED=1 \
    PATH="/home/myuser/.venv/bin:$PATH"

WORKDIR /home/myuser

# pyproject.toml points at the sibling checkout (../jobspy-py, editable) and at a
# China-only PyPI mirror. Neither exists inside a build context, so repoint both
# at public locations for the image. Override the args to build against a fork,
# a tag, or an internal mirror.
ARG PYPI_INDEX=https://pypi.org/simple
ARG JOBSPY_GIT=https://github.com/mecodes03/JobSpy.git
COPY --chown=myuser:myuser pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/home/myuser/.cache/uv \
    sed -i "s|https://pypi.tuna.tsinghua.edu.cn/simple|${PYPI_INDEX}|" pyproject.toml \
 && sed -i "s|jobspy-py = { path = \"../jobspy-py\", editable = true }|jobspy-py = { git = \"${JOBSPY_GIT}\" }|" pyproject.toml \
 && uv lock \
 && uv sync --locked --no-dev --no-install-project --extra api --extra apify

# Source last: dependency layers above stay cached across code edits.
COPY --chown=myuser:myuser src ./src
RUN --mount=type=cache,target=/home/myuser/.cache/uv \
    uv sync --locked --no-dev --extra api --extra apify

EXPOSE 4321

# Only meaningful in API mode; Apify ignores HEALTHCHECK.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import sys,urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:4321/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "job_board.serve"]
