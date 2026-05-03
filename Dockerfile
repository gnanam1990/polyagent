# PolyAgent — production image.
#
# IMPORTANT: passport.py shells out to the `kpass` CLI for Kite Passport
# session lookups. The image does NOT bundle kpass (its install path
# differs by platform). Mount or copy a `kpass` binary into the
# container's PATH at runtime, e.g.:
#
#   docker run -v $(which kpass):/usr/local/bin/kpass:ro polyagent
#
# /health works without kpass; auth-gated endpoints will return 403
# until kpass is reachable.

FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install -r requirements.txt


FROM python:3.13-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POLYAGENT_DB_PATH=/data/polyagent.db

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY polyagent ./polyagent

RUN groupadd --system polyagent \
 && useradd --system --gid polyagent --home /app polyagent \
 && mkdir -p /data \
 && chown -R polyagent:polyagent /app /data

USER polyagent

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"

CMD ["uvicorn", "polyagent.main:app", "--host", "0.0.0.0", "--port", "8000"]
