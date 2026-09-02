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
