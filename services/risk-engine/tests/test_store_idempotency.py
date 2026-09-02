from app.store import RiskStore


def _apply(store, event_id, symbol="AAPL", cash_delta=-1000.0, pos=10.0,
           price=100.0, account="acct_123"):
    return store.apply_ledger_event(
        event_id=event_id, account_id=account, symbol=symbol, side="BUY",
        quantity=10.0, price=price, cash_delta=cash_delta, position_after=pos,
        correlation_id="corr-1", posted_at="2026-09-01T12:00:00Z")


def test_duplicate_event_id_is_deduped(tmp_path):
    store = RiskStore(str(tmp_path / "risk.db"))
    assert _apply(store, "evt-1") is True     # newly applied
    assert _apply(store, "evt-1") is False    # duplicate -> no-op
    assert store.applied_count() == 1


def test_dedupe_survives_restart(tmp_path):
    db = str(tmp_path / "risk.db")
    store = RiskStore(db)
    assert _apply(store, "evt-1") is True
    store.close()  # simulate process exit

    # Fresh process/store on the SAME file must still know evt-1.
    restarted = RiskStore(db)
    assert restarted.already_applied("evt-1") is True
    assert _apply(restarted, "evt-1") is False   # still deduped across restart
    assert restarted.applied_count() == 1


def test_derived_cash_and_positions(tmp_path):
    store = RiskStore(str(tmp_path / "risk.db"))
    _apply(store, "evt-1", symbol="AAPL", cash_delta=-1000.0, pos=10.0, price=100.0)
    _apply(store, "evt-2", symbol="MSFT", cash_delta=-1000.0, pos=5.0, price=200.0)

    assert store.account_cash("acct_123", 10000.0) == 8000.0
    positions = {s: (q, p) for s, q, p in store.latest_positions("acct_123")}
    assert positions["AAPL"] == (10.0, 100.0)
    assert positions["MSFT"] == (5.0, 200.0)


def test_price_cache_overrides_trade_price(tmp_path):
    store = RiskStore(str(tmp_path / "risk.db"))
    _apply(store, "evt-1", symbol="AAPL", pos=10.0, price=100.0)
    # No tick yet -> fallback to trade price.
    assert store.resolved_positions("acct_123") == [("AAPL", 10.0, 100.0)]
    # Tick arrives -> resolved price prefers the live mark.
    store.upsert_price("AAPL", 130.0)
    assert store.resolved_positions("acct_123") == [("AAPL", 10.0, 130.0)]
