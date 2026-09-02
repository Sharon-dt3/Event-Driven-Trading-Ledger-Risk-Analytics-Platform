import pytest

from app.metrics import compute_metrics


def test_portfolio_value_and_pnl_are_live():
    # cash after a BUY of 10 @ 100 from seed 10000 -> 9000 cash, 10 shares.
    # marked at 120 -> market_value 1200 -> PV 10200 -> PnL +200.
    m = compute_metrics(cash=9000.0, positions=[("AAPL", 10.0, 120.0)],
                        seed_cash=10000.0)
    assert m.portfolio_value == pytest.approx(10200.0)
    assert m.pnl == pytest.approx(200.0)


def test_pnl_zero_when_marked_at_trade_price():
    # Marked at the trade price -> value equals cost -> PnL 0, PV == seed.
    m = compute_metrics(cash=9000.0, positions=[("AAPL", 10.0, 100.0)],
                        seed_cash=10000.0)
    assert m.portfolio_value == pytest.approx(10000.0)
    assert m.pnl == pytest.approx(0.0)


def test_history_metrics_are_zero_in_thin_slice():
    m = compute_metrics(cash=9000.0, positions=[("AAPL", 10.0, 120.0)],
                        seed_cash=10000.0)
    assert m.volatility == 0.0
    assert m.var == 0.0
    assert m.sharpe == 0.0
    assert m.var_method == "parametric"  # emitted per contract


def test_single_return_still_zero_volatility():
    # One return is not enough for population stddev -> stays 0 (POC guard).
    m = compute_metrics(cash=10000.0, positions=[], seed_cash=10000.0,
                        pv_returns=[0.01])
    assert m.volatility == 0.0 and m.var == 0.0 and m.sharpe == 0.0


def test_volatility_is_pstdev_of_pv_returns():
    # PV returns [0.01, -0.01]: pstdev = 0.01, mean = 0.
    # PV here = cash 10000 + 0 positions = 10000.
    # var = 1.65 * 0.01 * 10000 = 165.0 ; sharpe = 0/0.01 = 0.
    m = compute_metrics(cash=10000.0, positions=[], seed_cash=10000.0,
                        pv_returns=[0.01, -0.01])
    assert m.volatility == pytest.approx(0.01, abs=1e-9)
    assert m.var == pytest.approx(165.0, abs=1e-6)
    assert m.sharpe == pytest.approx(0.0, abs=1e-9)


def test_volatility_var_sharpe_hand_calc_nonzero_sharpe():
    # PV returns [0.01, 0.02, 0.03]: mean = 0.02,
    # pstdev = sqrt((1e-4 + 0 + 1e-4)/3) = 0.00816497,
    # sharpe = 0.02 / 0.00816497 = 2.4495,
    # var = 1.65 * 0.00816497 * 10000 = 134.72.
    m = compute_metrics(cash=10000.0, positions=[], seed_cash=10000.0,
                        pv_returns=[0.01, 0.02, 0.03])
    assert m.volatility == pytest.approx(0.008165, abs=1e-6)
    assert m.sharpe == pytest.approx(2.4495, abs=1e-4)
    assert m.var == pytest.approx(134.72, abs=1e-2)
