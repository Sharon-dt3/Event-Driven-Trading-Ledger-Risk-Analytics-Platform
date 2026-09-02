from app.config import Config
from app.consumer import RiskConsumer
from app.store import RiskStore


def _ledger_env(event_id, symbol="AAPL", side="BUY", qty=10, price=100.0,
                cash_delta=-1000.0, position_after=10, account="acct_123",
                correlation_id="corr-1"):
    return {
        "event_id": event_id,
        "event_type": "LedgerUpdated",
        "schema_version": "1",
        "correlation_id": correlation_id,
        "produced_at": "2026-09-01T12:00:00.500Z",
        "producer": "ledger-core",
        "data": {
            "journal_entry_id": "je_1001",
            "source_event_id": "0d1e2f3a-4b5c-6d7e-8f90-a1b2c3d4e5f6",
            "account_id": account, "symbol": symbol, "side": side,
            "quantity": qty, "price": price, "cash_delta": cash_delta,
            "position_after": position_after, "posted_at": "2026-09-01T12:00:00.500Z",
        },
    }


def _consumer(tmp_path):
    store = RiskStore(str(tmp_path / "risk.db"))
    return RiskConsumer(store, Config(db_path=str(tmp_path / "risk.db")))


def test_ledger_event_produces_contract_shaped_risk_event(tmp_path):
    consumer = _consumer(tmp_path)
    risk = consumer.process_ledger_envelope(_ledger_env("evt-1"))

    assert risk is not None
    assert risk["event_type"] == "RiskComputed"
    assert risk["producer"] == "risk-engine"
    assert risk["correlation_id"] == "corr-1"  # propagated
    data = risk["data"]
    # Contract requires exactly these 8 fields (additionalProperties:false).
    assert set(data.keys()) == {
        "account_id", "portfolio_value", "pnl", "volatility", "var",
        "var_method", "sharpe", "computed_at"}
    # Marked at trade price (no tick) -> PV == seed, PnL == 0.
    assert data["portfolio_value"] == 10000.0
    assert data["pnl"] == 0.0
    # Thin slice: history metrics present but zero.
    assert data["volatility"] == 0.0
    assert data["var"] == 0.0
    assert data["sharpe"] == 0.0


def test_duplicate_delivery_publishes_nothing(tmp_path):
    consumer = _consumer(tmp_path)
    assert consumer.process_ledger_envelope(_ledger_env("evt-1")) is not None
    # Same envelope event_id again -> durable dedupe -> no risk event.
    assert consumer.process_ledger_envelope(_ledger_env("evt-1")) is None


def test_tick_updates_mark_used_for_pv(tmp_path):
    consumer = _consumer(tmp_path)
    # Price tick first, then a trade -> PV reflects the live mark, PnL > 0.
    consumer.process_tick_envelope({
        "event_type": "TickReceived", "data": {"symbol": "AAPL", "price": 120.0}})
    risk = consumer.process_ledger_envelope(_ledger_env("evt-1"))
    assert risk["data"]["portfolio_value"] == 10200.0
    assert risk["data"]["pnl"] == 200.0


def test_malformed_event_is_skipped(tmp_path):
    consumer = _consumer(tmp_path)
    assert consumer.process_ledger_envelope({"data": {}}) is None
