"""TradePulse Risk Engine — FastAPI app: health/observability + Phase 6 read API.

Read API (frozen contract: docs/contracts/openapi/risk.openapi.yaml):
- ``GET /risk/summary?account_id=...`` -> latest ``RiskSummary``
- ``GET /risk/var?account_id=...``     -> ``VarDetail`` (parametric only)

Freshness model: the read API serves the **last-published** risk snapshot
straight from the durable store (``risk_snapshots``, written by the consumer as
each ``RiskComputed.v1`` is built and immediately published). A dashboard's
fetch-on-load is therefore coherent with the live ``risk.updates`` stream — the
REST answer matches the last event put on the wire, rather than a fresh
recompute that could diverge mid-throttle-interval.

Error shape: all error responses use the frozen contract's ``Error`` schema
(``{code, message}``) so the dashboard can code against a single documented
error shape. This includes FastAPI request-validation failures (422), which are
reshaped from the framework default ``{detail: [...]}`` to ``{code, message}``.

Auth note: bearer auth in the contract is enforced at the gateway/ALB edge, so
these in-service handlers do not re-check credentials.
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .config import from_env
from .correlation import (
    CORRELATION_HEADER,
    new_correlation_id,
    set_correlation_id,
)
from .explain import explain_snapshot
from .logging_config import configure_logging
from .store import RiskStore

configure_logging()
logger = logging.getLogger("risk-engine")

app = FastAPI(title="TradePulse Risk Engine", version="0.1.0")

# Parametric VaR characterisation (matches metrics.VAR_Z_95 ~ one-sided 95%,
# 1-day horizon). Surfaced in the VarDetail response.
VAR_CONFIDENCE = 0.95
VAR_HORIZON_DAYS = 1


class RiskApiError(Exception):
    """Application error carrying the contract ``Error`` shape (code+message)."""

    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """Build a contract-shaped ``{code, message}`` error response."""
    return JSONResponse(status_code=status_code,
                        content={"code": code, "message": message})


@app.exception_handler(RiskApiError)
async def _risk_api_error_handler(_request: Request, exc: RiskApiError):
    return _error(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def _validation_error_handler(_request: Request, exc: RequestValidationError):
    # Reshape FastAPI's default {detail: [...]} to the contract Error schema so
    # the dashboard sees one uniform error shape across all failure modes.
    try:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first.get("loc", []) if p != "query")
        message = f"{loc}: {first.get('msg')}" if loc else first.get("msg", "invalid request")
    except (IndexError, KeyError, TypeError):
        message = "invalid request"
    return _error(422, "validation_error", message)


def _open_store() -> RiskStore:
    """Open a short-lived store handle against the shared DB (read path).

    Reads ``RISK_DB_PATH`` live via ``from_env()`` so the API and the worker
    share the same SQLite file. Opened and closed per request, so each request
    uses its own connection on its own thread (sqlite ``check_same_thread`` safe)
    and always observes the worker's latest committed writes (WAL).
    """
    return RiskStore(from_env().db_path)


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


@app.get("/risk/summary")
def risk_summary(account_id: str):
    """Latest portfolio value, P&L, volatility, VaR, Sharpe for an account.

    Serves the last-published snapshot; returns 404 (contract ``Error`` shape)
    when no metrics have been computed for the account yet.
    """
    store = _open_store()
    try:
        snapshot = store.get_risk_snapshot(account_id)
    finally:
        store.close()
    if snapshot is None:
        raise RiskApiError(404, "not_found",
                           "No metrics computed yet for this account.")
    return snapshot


@app.get("/risk/var")
def risk_var(account_id: str, method: Optional[str] = None):
    """VaR detail (parametric only), including method/confidence/horizon.

    ``method=historical`` is explicitly rejected: historical VaR is a documented
    deferral for this slice (parametric-only). Missing accounts return 404 for
    consistency with ``/risk/summary``.
    """
    if method == "historical":
        raise RiskApiError(400, "unsupported_var_method",
                           "historical VaR is not supported; parametric only")
    store = _open_store()
    try:
        snapshot = store.get_risk_snapshot(account_id)
    finally:
        store.close()
    if snapshot is None:
        raise RiskApiError(404, "not_found",
                           "No metrics computed yet for this account.")
    return {
        "account_id": snapshot["account_id"],
        "var": snapshot["var"],
        "var_method": snapshot["var_method"],
        "confidence": VAR_CONFIDENCE,
        "horizon_days": VAR_HORIZON_DAYS,
        "computed_at": snapshot["computed_at"],
    }


@app.get("/risk/explain")
def risk_explain(account_id: str):
    """Plain-language explainability layer over the latest risk snapshot.

    Turns portfolio value, P&L, volatility, VaR and Sharpe into human-readable
    analysis for users without financial expertise. Additive to the frozen
    contracts (does not alter RiskSummary/RiskComputed). Returns 404 (contract
    ``Error`` shape) when no metrics have been computed for the account yet.

    Note: the store keeps only the latest snapshot per account, so this endpoint
    explains current *levels*. The dashboard generates the live "what changed and
    why" narrative by diffing consecutive ``risk.updates`` events client-side.
    """
    store = _open_store()
    try:
        snapshot = store.get_risk_snapshot(account_id)
    finally:
        store.close()
    if snapshot is None:
        raise RiskApiError(404, "not_found",
                           "No metrics computed yet for this account.")
    return explain_snapshot(snapshot)
