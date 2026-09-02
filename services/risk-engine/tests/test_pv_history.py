"""Step 2 (model A): pv_history — the portfolio-value return series that
volatility/VaR/Sharpe consume. Same rolling-window/eviction/restart-durable
properties proven for price_history in step 1, applied to per-account PV.
"""
import os
import tempfile

import pytest

from app.store import RiskStore


def _store(tmp):
    return RiskStore(os.path.join(tmp, "risk_state.db"))


def test_pv_window_fills_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for pv in (10000.0, 10100.0, 9999.0):
            s.append_pv("acct", pv, window_size=30)
        assert s.pv_window("acct") == [10000.0, 10100.0, 9999.0]
        assert s.pv_history_len("acct") == 3
        s.close()


def test_pv_eviction_keeps_window_plus_one_in_order():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for pv in range(1, 36):  # 1..35 @ window_size=30 -> keep last 31 (5..35)
            s.append_pv("acct", float(pv), window_size=30)
        assert s.pv_window("acct") == [float(pv) for pv in range(5, 36)]
        assert s.pv_history_len("acct") == 31
        assert len(s.pv_returns("acct")) == 30
        s.close()


def test_pv_returns_hand_calc():
    # PV [10000, 10100, 9999] -> returns [0.01, (9999-10100)/10100].
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        for pv in (10000.0, 10100.0, 9999.0):
            s.append_pv("acct", pv, window_size=30)
        assert s.pv_returns("acct") == pytest.approx(
            [0.01, (9999.0 - 10100.0) / 10100.0])
        s.close()


def test_pv_history_is_per_account():
    with tempfile.TemporaryDirectory() as tmp:
        s = _store(tmp)
        s.append_pv("a", 10000.0, window_size=30)
        s.append_pv("b", 20000.0, window_size=30)
        s.append_pv("a", 10100.0, window_size=30)
        assert s.pv_window("a") == [10000.0, 10100.0]
        assert s.pv_window("b") == [20000.0]
        s.close()


def test_pv_history_survives_restart():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "risk_state.db")
        s1 = RiskStore(db)
        for pv in (10000.0, 10100.0, 9999.0):
            s1.append_pv("acct", pv, window_size=30)
        s1.close()
        s2 = RiskStore(db)  # fresh store, same file
        assert s2.pv_window("acct") == [10000.0, 10100.0, 9999.0]
        assert s2.pv_returns("acct") == pytest.approx(
            [0.01, (9999.0 - 10100.0) / 10100.0])
        s2.close()
