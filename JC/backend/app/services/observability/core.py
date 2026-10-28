"""Request correlation + error tracking wiring.

Both pieces are opt-in via env vars so local dev / tests need nothing extra:
- SENTRY_DSN unset -> Sentry is simply never initialized.
- Every request still gets a request id in logs and in the `X-Request-ID`
  response header even without Sentry, so a user-reported error can be
  grep'd out of Railway logs.
"""

from __future__ import annotations

import contextvars
import logging
import uuid

from fastapi import FastAPI, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")


def get_request_id() -> str:
    return _request_id_ctx.get()


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        return True


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        token = _request_id_ctx.set(rid)
        try:
            response = await call_next(request)
        finally:
            _request_id_ctx.reset(token)
        response.headers["X-Request-ID"] = rid
        return response


def configure_logging() -> None:
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [req=%(request_id)s] %(name)s %(message)s"
    ))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


def init_sentry() -> None:
    s = get_settings()
    if not s.sentry_dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger(__name__).warning(
            "SENTRY_DSN is set but sentry-sdk is not installed — run `pip install sentry-sdk`"
        )
        return
    sentry_sdk.init(
        dsn=s.sentry_dsn,
        environment=s.environment,
        traces_sample_rate=0.1,
        send_default_pii=False,
    )


def setup_observability(app: FastAPI) -> None:
    configure_logging()
    init_sentry()
    app.add_middleware(RequestIdMiddleware)
