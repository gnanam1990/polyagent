"""Structured logging for PolyAgent.

A request_id contextvar is populated by RequestIdMiddleware. The custom
formatter emits a single line of `key=value` pairs ending with the message,
which is easy to grep and easy to ship to a log aggregator that parses
logfmt. We keep this stdlib-only so we don't pull in structlog.
"""

from __future__ import annotations

import logging
import os
import sys
import time
import uuid
from contextvars import ContextVar

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
_request_id: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id.get()


class _LogfmtFormatter(logging.Formatter):
    """Format records as `ts=... level=... logger=... request_id=... msg="..."`."""

    def format(self, record: logging.LogRecord) -> str:
        ts = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
        ts = f"{ts}.{int(record.msecs):03d}Z"
        msg = record.getMessage().replace('"', '\\"')
        parts = [
            f"ts={ts}",
            f"level={record.levelname}",
            f"logger={record.name}",
            f"request_id={_request_id.get()}",
            f'msg="{msg}"',
        ]
        if record.exc_info:
            parts.append(f'exc="{self.formatException(record.exc_info)}"')
        return " ".join(parts)


def configure_logging(level: str | None = None) -> None:
    """Idempotently configure the root logger."""
    level_name = (level or os.environ.get("POLYAGENT_LOG_LEVEL") or "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_LogfmtFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level_name)
    # Quiet uvicorn's default access logger — we emit our own access line.
    logging.getLogger("uvicorn.access").disabled = True


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Generate or pass through a request id, set the contextvar, log access."""

    def __init__(self, app, logger_name: str = "polyagent.access") -> None:
        super().__init__(app)
        self._log = logging.getLogger(logger_name)

    async def dispatch(self, request: Request, call_next) -> Response:
        rid = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:12]
        token = _request_id.set(rid)
        start = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = rid
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self._log.info(
                "%s %s -> %d in %.1fms",
                request.method,
                request.url.path,
                status,
                duration_ms,
            )
            _request_id.reset(token)
