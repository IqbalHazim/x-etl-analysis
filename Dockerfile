FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    MPLBACKEND=Agg

WORKDIR /app

# Dependencies first, so code changes don't reinstall them.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY src ./src
COPY config ./config
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Recorded in each run manifest: GIT_SHA=$(git rev-parse --short HEAD) docker compose build
ARG GIT_SHA=unknown
ENV XETL_GIT_SHA=$GIT_SHA

# UID 1000 matches the default WSL user, so files written to data/ stay editable.
RUN useradd --uid 1000 --create-home xetl
USER xetl

ENTRYPOINT ["xetl"]
CMD ["--help"]
