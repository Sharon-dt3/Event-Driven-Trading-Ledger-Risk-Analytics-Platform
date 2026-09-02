"""TradePulse Risk Engine — Phase 1 skeleton (health + observability)."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request

from .correlation import (
    CORRELATION_HEADER,
    new_correlation_id,
    set_correlation_id,
)
from .logging_config import configure_logging

configure_logging()
logger = logging.getLogger("risk-engine")

app = FastAPI(title="TradePulse Risk Engine", version="0.1.0")


@app.middleware("http")
async def correlation_middleware(request: Request, call_next):
    cid = request.headers.get(CORRELATION_HEADER) or new_correlation_id()
    set_correlation_id(cid)
    response = await call_next(request)
    response.headers[CORRELATION_HEADER] = cid
    logger.info(
        "http_request",
        extra={
            "extra_fields": {
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
            }
        },
    )
    return response


@app.get("/health")
@app.get("/healthz")
async def health():
    return {"status": "UP", "service": "risk-engine"}


@app.get("/")
async def root():
    return {"service": "risk-engine", "version": "0.1.0"}
