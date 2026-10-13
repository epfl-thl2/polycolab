FROM node:26.5.0-bookworm-slim AS web

# The Node image does not bundle Corepack; install the exact pnpm version
# declared in package.json using pnpm's standalone installer.
RUN apt-get update \
  && apt-get install --yes --no-install-recommends ca-certificates curl \
  && rm -rf /var/lib/apt/lists/*
ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME/bin:$PATH"
RUN curl -fsSL https://get.pnpm.io/install.sh | env PNPM_VERSION=12.1.0 PNPM_HOME=/pnpm SHELL=sh ENV=/dev/null sh -

WORKDIR /workspace
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY src/web/package.json src/web/package.json
COPY src/collaboration/package.json src/collaboration/package.json
RUN pnpm install --frozen-lockfile
COPY docs-site/vite-plugin.mjs docs-site/sync-brand.mjs docs-site/
COPY src/web src/web
COPY skills skills
# Feature availability is read from the API at runtime by the same web image.
ARG VITE_RELEASE_ID=
ARG VITE_FEEDBACK_URL=
# Allow sufficient memory for the Vite production build.
ARG WEB_BUILD_NODE_OPTIONS=--max-old-space-size=4096
RUN NODE_OPTIONS="$WEB_BUILD_NODE_OPTIONS" \
     VITE_RELEASE_ID="$VITE_RELEASE_ID" VITE_FEEDBACK_URL="$VITE_FEEDBACK_URL" \
     pnpm --filter @polycolab/web run build

FROM ghcr.io/astral-sh/uv:0.10.10 AS uv

FROM python:3.14.0-slim-bookworm AS docs

COPY --from=uv /uv /uvx /bin/
WORKDIR /workspace
COPY docs-site/pyproject.toml docs-site/uv.lock docs-site/
RUN uv sync --project docs-site --frozen
COPY docs-site docs-site
COPY src/web/src/styles/tokens.css docs-site/docs/styles/brand-tokens.css
RUN uv run --project docs-site zensical build --clean --strict \
       --config-file docs-site/mkdocs.yml

FROM python:3.14.0-slim-bookworm

RUN apt-get update && apt-get install --yes --no-install-recommends git && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PATH="/app/.venv/bin:$PATH"
ENV WEB_DIST_DIR="/app/web-dist"
WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY src/backend/pyproject.toml src/backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/backend ./
RUN uv sync --frozen --no-dev
COPY --from=web /workspace/src/web/dist ./web-dist
COPY --from=docs /workspace/docs-site/site ./web-dist/docs

EXPOSE 8000
CMD ["uvicorn", "polycolab.main:app", "--host", "0.0.0.0", "--port", "8000"]
