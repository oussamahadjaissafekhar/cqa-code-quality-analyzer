# syntax=docker/dockerfile:1.7
#
# Optimized multi-stage image for the CQA CLI.
#
#   node-build   -> compiles the TypeScript syntax parser
#   python-build -> installs the Python CLI into a self-contained venv
#   runtime      -> slim Debian image with the venv, the Node runtime, and the
#                   compiled parser packages (no npm, compilers, or build cache)
#
# The runtime image is built for the same platform as the node/python stages,
# so the Node binary can be copied instead of downloaded with curl/xz.

ARG PYTHON_VERSION=3.12
ARG CQA_VERSION=0.1.0

# ---------------------------------------------------------------------------
# Stage 1: build the TypeScript parser packages
# ---------------------------------------------------------------------------
FROM node:20-bookworm-slim AS node-build

WORKDIR /build

# Install dependencies in a cacheable layer keyed only on the manifests.
COPY package.json package-lock.json tsconfig.base.json ./
COPY packages ./packages
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

# Compile shared -> parser-core -> parser-cli.
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: install the Python CLI into an isolated virtualenv
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS python-build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

COPY pyproject.toml README.md LICENSE ./
COPY src ./src

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m venv /opt/cqa/venv \
    && /opt/cqa/venv/bin/pip install --upgrade pip \
    && /opt/cqa/venv/bin/pip install .

# ---------------------------------------------------------------------------
# Stage 3: minimal runtime
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime

ARG CQA_VERSION=0.1.0
ARG CQA_REVISION=unknown

# libstdc++6 is required by the Node binary copied from the build stage.
# Version pins are intentionally omitted so rebuilds pick up Debian security
# updates; the base image digest already pins the starting point.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

# Node is only used to execute the parser subprocess; npm is not needed here.
COPY --from=node-build /usr/local/bin/node /usr/local/bin/node

# Python CLI and its console script.
COPY --from=python-build /opt/cqa/venv /opt/cqa/venv

# Compiled parser entrypoint plus the workspace packages it imports. Placing
# them under /opt/cqa/node_modules lets Node resolve `@cqa/*` from
# /opt/cqa/parser-cli.js without shipping the full npm dependency tree.
COPY --from=node-build /build/packages/parser-cli/dist/main.js /opt/cqa/parser-cli.js
COPY --from=node-build /build/packages/shared/dist /opt/cqa/node_modules/@cqa/shared/dist
COPY --from=node-build /build/packages/shared/package.json /opt/cqa/node_modules/@cqa/shared/package.json
COPY --from=node-build /build/packages/parser-core/dist /opt/cqa/node_modules/@cqa/parser-core/dist
COPY --from=node-build /build/packages/parser-core/package.json /opt/cqa/node_modules/@cqa/parser-core/package.json

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod 0755 /entrypoint.sh \
    && groupadd --gid 1000 cqa \
    && useradd --uid 1000 --gid cqa --create-home --home-dir /home/cqa cqa \
    && chown -R cqa:cqa /opt/cqa

ENV PATH="/opt/cqa/venv/bin:${PATH}" \
    CQA_PARSER_BIN=/opt/cqa/parser-cli.js \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    NODE_NO_WARNINGS=1

LABEL org.opencontainers.image.title="cqa" \
      org.opencontainers.image.description="Code Quality Analyzer CLI (Python + TypeScript parser)" \
      org.opencontainers.image.source="https://github.com/cqa-project/cqa" \
      org.opencontainers.image.version="${CQA_VERSION}" \
      org.opencontainers.image.revision="${CQA_REVISION}" \
      org.opencontainers.image.licenses="MIT" \
      cqa.schema_version="1"

WORKDIR /workspace
USER 1000:1000

ENTRYPOINT ["/entrypoint.sh"]
CMD ["--help"]
