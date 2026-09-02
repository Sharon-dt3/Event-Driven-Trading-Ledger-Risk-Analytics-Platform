"""Portfolio metric computation (pure, Redis-free, unit-testable).

- **portfolio_value** and **P&L** are computed from current cash + marked
  positions (ledger-driven, always live).
- **volatility, VaR, Sharpe** are computed over a *portfolio-value return
  series* (model A, matching `poc/end-to-end/risk_engine.py`): the 2B throttle
  samples portfolio value on an interval into `pv_history`, and the consecutive
  PV returns feed these statistics. When fewer than two returns exist (window
  still filling), the three are emitted as `0.0` so every published event still
  satisfies the `RiskComputed.v1` contract (`additionalProperties:false`
  requires all fields present).

IMPORTANT (scope/honesty): a published `var: 0` means "not enough history yet",
NOT "there is no risk". VaR is **parametric only** (~95% one-sided z=1.65);
historical VaR is out of scope for this slice.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple

# Parametric one-sided ~95% z-score (matches the POC / Phase 0 default).
VAR_Z_95 = 1.65


@dataclass(frozen=True)
class RiskMetrics:
    portfolio_value: float
    pnl: float
    volatility: float
    var: float
    var_method: str
    sharpe: float


def _history_metrics(portfolio_value: float,
                     pv_returns: Optional[Sequence[float]]) -> Tuple[float, float, float]:
    """(volatility, var, sharpe) over a PV-return series, POC-faithful.

    - volatility = population stddev of PV returns (needs > 1 return).
    - var        = |z * volatility * portfolio_value|  (parametric, ~95%).
    - sharpe     = mean(returns) / volatility          (0 when volatility == 0).
    """
    returns = [float(r) for r in pv_returns] if pv_returns else []
    volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
    var = abs(VAR_Z_95 * volatility * portfolio_value)
    sharpe = (statistics.mean(returns) / volatility) if volatility > 0 else 0.0
    return volatility, var, sharpe


def compute_metrics(cash: float,
                    positions: Iterable[Tuple[str, float, float]],
                    seed_cash: float,
                    *, var_method: str = "parametric",
                    pv_returns: Optional[Sequence[float]] = None) -> RiskMetrics:
    """Compute portfolio metrics.

    :param cash: current cash = seed + sum(cash_delta)
    :param positions: iterable of (symbol, qty, resolved_price)
    :param seed_cash: portfolio-value baseline
    :param pv_returns: portfolio-value return series (model A); when omitted or
        shorter than two points, volatility/VaR/Sharpe are 0.0.
    :returns: RiskMetrics with PV + P&L live; history metrics live once the PV
        return series has accrued at least two returns.
    """
    market_value = sum(qty * price for _symbol, qty, price in positions)
    portfolio_value = cash + market_value
    pnl = portfolio_value - seed_cash

    volatility, var, sharpe = _history_metrics(portfolio_value, pv_returns)

    return RiskMetrics(
        portfolio_value=round(portfolio_value, 2),
        pnl=round(pnl, 2),
        volatility=round(volatility, 6),
        var=round(var, 2),
        var_method=var_method,
        sharpe=round(sharpe, 4),
    )
