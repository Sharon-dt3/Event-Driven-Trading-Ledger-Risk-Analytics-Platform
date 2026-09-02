"""Phase 6 read API tests (offline; no Redis).

Covers the frozen risk read API (docs/contracts/openapi/risk.openapi.yaml):
- /risk/summary and /risk/var serve the last-published snapshot from the store,
- 404 before any metrics exist, 422 when account_id is missing,
- historical VaR is rejected (parametric-only deferral),
- error bodies use the contract Error shape {code, message},
- and the consumer persists a snapshot that matches the published envelope for
  BOTH the 2A ledger-driven path and the 2B throttle path.
"""
from fastapi.testclient import TestClient

from app.config import Config
from app.consumer import RiskConsumer
from app.main import app
from app.store import RiskStore

client = TestClient(app)


def _seed(db_path, account_id="acct-1"):
    store = RiskStore(str(db_path))
    store.save_risk_snapshot(
        account_id=account_id,
        portfolio_value=10500.0,
        pnl=500.0,
        volatility=0.0123,
        var=213.45,
        var_method="parametric",
        sharpe=0.42,
        computed_at="2026-01-01T00:00:00+00:00",
    )
    store.close()


def _ledger_envelope(event_id, account_id="acct-9", symbol="AAPL",
                     cash_delta=-1000.0, position_after=10.0, price=100.0):
    return {
        "event_id": event_id,
        "event_type": "LedgerUpdated",
        "schema_version": "1",
        "correlation_id": "corr-1",
        "data": {
            "account_id": account_id,
            "symbol": symbol,
            "side": "BUY",
            "quantity": 10.0,
            "price": price,
            "cash_delta": cash_delta,
            "position_after": position_after,
            "posted_at": "2026-01-01T00:00:00+00:00",
        },
    }


def test_summary_returns_last_snapshot(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    _seed(db)
    resp = client.get("/risk/summary", params={"account_id": "acct-1"})
    assert resp.status_code == 200
    assert resp.json() == {
        "account_id": "acct-1",
        "portfolio_value": 10500.0,
        "pnl": 500.0,
        "volatility": 0.0123,
        "var": 213.45,
        "var_method": "parametric",
        "sharpe": 0.42,
        "computed_at": "2026-01-01T00:00:00+00:00",
    }


def test_summary_404_when_no_metrics(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    _seed(db)
    resp = client.get("/risk/summary", params={"account_id": "missing"})
    assert resp.status_code == 404
    assert resp.json() == {"code": "not_found",
                           "message": "No metrics computed yet for this account."}


def test_summary_requires_account_id(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    _seed(db)
    resp = client.get("/risk/summary")
    assert resp.status_code == 422  # FastAPI validation: required query param
    body = resp.json()
    assert body["code"] == "validation_error"
    assert "message" in body


def test_var_detail_parametric(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    _seed(db)
    resp = client.get("/risk/var", params={"account_id": "acct-1"})
    assert resp.status_code == 200
    assert resp.json() == {
        "account_id": "acct-1",
        "var": 213.45,
        "var_method": "parametric",
        "confidence": 0.95,
        "horizon_days": 1,
        "computed_at": "2026-01-01T00:00:00+00:00",
    }


def test_var_historical_rejected(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    _seed(db)
    resp = client.get(
        "/risk/var", params={"account_id": "acct-1", "method": "historical"}
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "unsupported_var_method"


def test_var_404_when_no_metrics(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    _seed(db)
    resp = client.get("/risk/var", params={"account_id": "nope"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_consumer_ledger_path_persists_matching_snapshot(tmp_path):
    """2A: the snapshot the REST API serves equals what the ledger path publishes."""
    db = tmp_path / "consumer.db"
    store = RiskStore(str(db))
    consumer = RiskConsumer(store, Config(db_path=str(db)))

    envelope = consumer.process_ledger_envelope(_ledger_envelope("evt-1"))
    assert envelope is not None
    snapshot = store.get_risk_snapshot("acct-9")
    store.close()

    assert snapshot is not None
    data = envelope["data"]
    assert snapshot["account_id"] == data["account_id"]
    assert snapshot["computed_at"] == data["computed_at"]
    assert snapshot["portfolio_value"] == data["portfolio_value"]
    assert snapshot["pnl"] == data["pnl"]
    assert snapshot["var"] == data["var"]
    assert snapshot["var_method"] == data["var_method"]
    assert snapshot["sharpe"] == data["sharpe"]


def test_consumer_throttle_path_persists_matching_snapshot(tmp_path):
    """2B: the throttle recompute path also updates the served snapshot."""
    db = tmp_path / "throttle.db"
    store = RiskStore(str(db))
    consumer = RiskConsumer(store, Config(db_path=str(db)))

    # A position must exist for the throttle to have something to value.
    consumer.process_ledger_envelope(_ledger_envelope("evt-1"))
    # Simulate a market move, then a throttle-driven recompute (2B).
    store.upsert_price("AAPL", 110.0)
    envelope = consumer.recompute_account("acct-9", "corr-2")
    assert envelope is not None

    snapshot = store.get_risk_snapshot("acct-9")
    store.close()

    assert snapshot is not None
    data = envelope["data"]
    # The throttle snapshot is the latest served state (coherent with stream).
    assert snapshot["computed_at"] == data["computed_at"]
    assert snapshot["portfolio_value"] == data["portfolio_value"]
    assert snapshot["var"] == data["var"]
