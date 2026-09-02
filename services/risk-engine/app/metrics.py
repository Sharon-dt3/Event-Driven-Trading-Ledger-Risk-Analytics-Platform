"""Portfolio metric computation (pure, Redis-free, unit-testable).

Phase 6 thin slice (1A): **portfolio value** and **P&L** are meaningfully
computed from current cash + marked positions. **volatility, VaR, and Sharpe**
require a portfolio-value return history, which only accrues once the
price-tick-driven recompute path is added; until then they are emitted as `0.0`
so every published event still satisfies the `RiskComputed.v1` contract
(`additionalProperties:false` requires all fields present).

IMPORTANT (scope/honesty): a published `var: 0` here means "not yet computed",
NOT "there is no risk". These three become live in the follow-on slice.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple


@dataclass(frozen=True)
class RiskMetrics:
    portfolio_value: float
    pnl: float
    volatility: float
    var: float
    var_method: str
    sharpe: float


def compute_metrics(cash: float,
                    positions: Iterable[Tuple[str, float, float]],
                    seed_cash: float,
                    *, var_method: str = "parametric") -> RiskMetrics:
    """Compute thin-slice metrics.

    :param cash: current cash = seed + sum(cash_delta)
    :param positions: iterable of (symbol, qty, resolved_price)
    :param seed_cash: portfolio-value baseline
    :returns: RiskMetrics with PV + P&L live; vol/VaR/Sharpe = 0 (thin slice)
    """
    market_value = sum(qty * price for _symbol, qty, price in positions)
    portfolio_value = cash + market_value
    pnl = portfolio_value - seed_cash

    # Thin slice: no return history yet -> the three history-based metrics are
    # emitted per contract but not yet meaningfully computed.
    volatility = 0.0
    var = 0.0
    sharpe = 0.0

    return RiskMetrics(
        portfolio_value=round(portfolio_value, 2),
        pnl=round(pnl, 2),
        volatility=round(volatility, 6),
        var=round(var, 2),
        var_method=var_method,
        sharpe=round(sharpe, 4),
    )
