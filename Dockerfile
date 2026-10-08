FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS runtime

ARG SOURCE_MANIFEST_SHA256
ARG SOURCE_CANDIDATE_ID

LABEL org.opencontainers.image.source-manifest-sha256=$SOURCE_MANIFEST_SHA256 \
      org.opencontainers.image.source-candidate=$SOURCE_CANDIDATE_ID

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

RUN test -n "$SOURCE_MANIFEST_SHA256" \
    && test "$SOURCE_MANIFEST_SHA256" != "UNBOUND" \
    && test "${#SOURCE_MANIFEST_SHA256}" -eq 64 \
    && case "$SOURCE_MANIFEST_SHA256" in *[!0-9a-f]*) exit 1 ;; esac \
    && test -n "$SOURCE_CANDIDATE_ID" \
    && test "$SOURCE_CANDIDATE_ID" != "UNBOUND" \
    && test "${#SOURCE_CANDIDATE_ID}" -eq 44 \
    && case "$SOURCE_CANDIDATE_ID" in git:*) ;; *) exit 1 ;; esac \
    && case "${SOURCE_CANDIDATE_ID#git:}" in *[!0-9a-f]*) exit 1 ;; esac

COPY pyproject.toml ./
COPY requirements.lock ./

RUN python -m pip install --no-cache-dir --require-hashes -r requirements.lock

COPY app ./app
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

RUN groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000 8501

FROM runtime AS test

USER root
COPY requirements.dev.lock ./
RUN python -m pip install --no-cache-dir -r requirements.dev.lock \
    && python -m pip install --no-cache-dir --no-deps ".[dev]"
USER appuser

FROM runtime AS production

USER root
RUN python -m pip uninstall --yes pip
USER appuser
