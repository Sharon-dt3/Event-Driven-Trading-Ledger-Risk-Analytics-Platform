"""Step 1 (Phase 6 widening): price-history infrastructure.

Proves the rolling per-symbol window fills in order, evicts correctly, and
derives a return series that matches a hand calculation -- before any metric
(volatility/VaR/sharpe) is computed on top of it. Ticks-only; durable by file.
"""
import os
import tempfile

import pytest

from app.config import Config
from app.consumer import RiskConsumer
from app.store import RiskStore


def _store(tmp):
    return RiskStore(os.path.join(tmp, "risk_state.db"))


def test_window_fills_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for p in (100.0, 101.0, 102.0):
            s.append_price("AAPL", p, window_size=30)
        assert s.price_window("AAPL") == [100.0, 101.0, 102.0]  # oldest->newest
        assert s.history_len("AAPL") == 3
        s.close()


def test_eviction_keeps_window_size_plus_one_prices():
    # window_size = returns retained; store keeps window_size + 1 prices.
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for p in (100.0, 101.0, 102.0, 103.0, 104.0):
            s.append_price("AAPL", p, window_size=3)
        # keep 4 most recent prices -> 3 returns derivable
        assert s.price_window("AAPL") == [101.0, 102.0, 103.0, 104.0]
        assert s.history_len("AAPL") == 4
        assert len(s.returns("AAPL")) == 3
        s.close()


def test_eviction_large_sequence_keeps_last_window_plus_one_in_order():
    # Fill 1..35 at window_size=30: keep exactly the last 31 prices (5..35),
    # oldest->newest. Asserts contents, not just length -- guards off-by-one on
    # the cap and evicting the wrong end.
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for p in range(1, 36):
            s.append_price("AAPL", float(p), window_size=30)
        assert s.price_window("AAPL") == [float(p) for p in range(5, 36)]
        assert s.history_len("AAPL") == 31
        assert len(s.returns("AAPL")) == 30  # window_size returns exactly
        s.close()


def test_returns_are_simple_not_log():
    # Convention pinned to SIMPLE returns (p_i - p_{i-1})/p_{i-1}, matching the
    # POC reference (poc/end-to-end/risk_engine.py). [100,110,99] -> [0.10,-0.10].
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for p in (100.0, 110.0, 99.0):
            s.append_price("SYM", p, window_size=30)
        assert s.returns("SYM") == pytest.approx([0.10, -0.10])
        s.close()


def test_returns_match_hand_calculation():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for p in (100.0, 101.0, 102.0, 101.5):
            s.append_price("AAPL", p, window_size=30)
        r = s.returns("AAPL")
        # r1=(101-100)/100, r2=(102-101)/101, r3=(101.5-102)/102
        assert r == pytest.approx([0.01, 1.0 / 101.0, -0.5 / 102.0])
        s.close()


def test_window_is_per_symbol():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        s.append_price("AAPL", 100.0, window_size=30)
        s.append_price("MSFT", 200.0, window_size=30)
        s.append_price("AAPL", 101.0, window_size=30)
        assert s.price_window("AAPL") == [100.0, 101.0]
        assert s.price_window("MSFT") == [200.0]
        s.close()


def test_history_survives_restart():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "risk_state.db")
        s1 = RiskStore(db)
        for p in (100.0, 101.0, 102.0):
            s1.append_price("AAPL", p, window_size=30)
        s1.close()
        # Fresh store on the same file still has the window.
        s2 = RiskStore(db)
        assert s2.price_window("AAPL") == [100.0, 101.0, 102.0]
        assert s2.returns("AAPL") == pytest.approx([0.01, 1.0 / 101.0])
        s2.close()


def test_consumer_tick_appends_to_history_and_cache():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        c = RiskConsumer(s, Config(db_path=os.path.join(tmp, "x"), window_size=30))
        for p in (100.0, 101.0):
            ok = c.process_tick_envelope(
                {"data": {"symbol": "AAPL", "price": p, "tick_time": "t"}})
            assert ok is True
        assert s.price_window("AAPL") == [100.0, 101.0]
        assert s.get_price("AAPL") == 101.0  # cache still updated for PV path
        s.close()


def test_empty_history_has_no_returns():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        assert s.price_window("AAPL") == []
        assert s.returns("AAPL") == []
        assert s.history_len("AAPL") == 0
        s.close()
