"""Risk explainability layer (pure, Redis-free, unit-testable).

Turns a RiskComputed/RiskSummary snapshot into plain-language analysis so users
*without* financial expertise understand what each number means and — when a
prior snapshot is supplied — *why* it changed as they trade.

Scope / contract safety: this module is purely additive. It does NOT alter the
frozen ``RiskComputed.v1`` event schema or the ``RiskSummary`` / ``VarDetail``
REST schemas; it only *derives* narrative text from an existing snapshot. The
backend ``/risk/explain`` endpoint serves a level-based explanation of the
latest stored snapshot (the store keeps only the latest per account), while the
dashboard generates the live "what changed and why" narrative by diffing
consecutive ``risk.updates`` events client-side.

Design notes:
- ``seed_cash`` is recovered exactly as ``portfolio_value - pnl`` (P&L is defined
  as ``portfolio_value - seed_cash``), so no configuration is needed here.
- ``volatility`` is the population stddev of portfolio-value returns over a short
  rolling window; ``var = 1.65 * volatility * portfolio_value`` (parametric,
  ~95%, 1-day); ``sharpe = mean(returns) / volatility``. The narrative explains
  these relationships in plain terms and mirrors the frontend ``explain.js``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

VAR_CONFIDENCE = 0.95
VAR_HORIZON_DAYS = 1

# Volatility bands (population stddev of per-interval PV returns, a fraction).
_VOL_VERY_LOW = 0.001
_VOL_LOW = 0.005
_VOL_MODERATE = 0.02


def _money(x: float) -> str:
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _signed_money(x: float) -> str:
    try:
        x = float(x)
    except (TypeError, ValueError):
        x = 0.0
    return f"{'+' if x >= 0 else '-'}{_money(abs(x))}"


def _pct(x: float, digits: int = 2) -> str:
    try:
        return f"{float(x) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "0.00%"


def _num(x: float, digits: int = 2) -> str:
    try:
        return f"{float(x):.{digits}f}"
    except (TypeError, ValueError):
        return "0.00"


def _f(snapshot: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        v = snapshot.get(key, default)
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _vol_band(volatility: float) -> str:
    if volatility <= 0:
        return "not measurable yet"
    if volatility < _VOL_VERY_LOW:
        return "very calm"
    if volatility < _VOL_LOW:
        return "low"
    if volatility < _VOL_MODERATE:
        return "moderate"
    return "elevated"


def _sharpe_band(sharpe: float, volatility: float) -> str:
    if volatility <= 0:
        return "not measurable yet"
    if sharpe >= 1.0:
        return "strong"
    if sharpe > 0:
        return "modestly positive"
    if sharpe == 0:
        return "flat"
    return "negative"


def _metrics(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    pv = _f(snapshot, "portfolio_value")
    pnl = _f(snapshot, "pnl")
    vol = _f(snapshot, "volatility")
    var = _f(snapshot, "var")
    sharpe = _f(snapshot, "sharpe")
    seed = round(pv - pnl, 2)
    pnl_pct = (pnl / seed) if seed else 0.0
    var_pct = (var / pv) if pv else 0.0

    metrics: List[Dict[str, Any]] = []

    metrics.append({
        "key": "portfolio_value",
        "label": "Portfolio value",
        "value": pv,
        "plain": (
            f"This is what your account is worth right now — your cash plus the "
            f"market value of your holdings priced at the latest market ticks. "
            f"It currently stands at {_money(pv)}."
        ),
    })

    if pnl >= 0:
        pnl_plain = (
            f"You're up {_money(pnl)} ({_pct(pnl_pct, 1)}) compared with your "
            f"starting cash of {_money(seed)}. This is an on-paper (unrealized) "
            f"gain: it moves with market prices and isn't locked in until you sell."
        )
    else:
        pnl_plain = (
            f"You're down {_money(abs(pnl))} ({_pct(pnl_pct, 1)}) compared with "
            f"your starting cash of {_money(seed)}. This is an on-paper "
            f"(unrealized) loss and will move back up if prices recover."
        )
    metrics.append({"key": "pnl", "label": "P&L", "value": pnl, "plain": pnl_plain})

    if vol <= 0:
        vol_plain = (
            "Volatility measures how much your portfolio value bounces around "
            "between updates. There isn't enough price history yet to measure it "
            "— it fills in after a short while of live prices."
        )
    else:
        vol_plain = (
            f"Volatility measures how much your portfolio value swings between "
            f"updates. At {_pct(vol)} it's currently {_vol_band(vol)} — a higher "
            f"number means bigger swings both up and down."
        )
    metrics.append({"key": "volatility", "label": "Volatility", "value": vol, "plain": vol_plain})

    if var <= 0:
        var_plain = (
            "Value at Risk (VaR) estimates your likely worst-case loss on a "
            "normal day. There isn't enough history yet to compute it."
        )
    else:
        var_plain = (
            f"Value at Risk (VaR) estimates your downside on a normal day. With "
            f"about {int(VAR_CONFIDENCE * 100)}% confidence, you wouldn't expect "
            f"to lose more than {_money(var)} over {VAR_HORIZON_DAYS} trading day "
            f"— roughly {_pct(var_pct)} of your portfolio. It rises when either "
            f"your volatility or your portfolio size grows."
        )
    metrics.append({"key": "var", "label": "VaR", "value": var, "plain": var_plain})

    band = _sharpe_band(sharpe, vol)
    if vol <= 0:
        sharpe_plain = (
            "The Sharpe ratio compares your recent return against how bumpy the "
            "ride was. Not enough history yet to compute it."
        )
    elif sharpe < 0:
        sharpe_plain = (
            f"The Sharpe ratio ({_num(sharpe)}) is your recent return per unit of "
            f"risk. It's {band}: over the recent window your portfolio drifted "
            f"down on average. This is a short-window figure that flips easily and "
            f"does not contradict a positive overall P&L."
        )
    else:
        sharpe_plain = (
            f"The Sharpe ratio ({_num(sharpe)}) is your recent return per unit of "
            f"risk over the recent window — it's {band}. Higher is better; it "
            f"rewards steady gains and penalizes big swings."
        )
    metrics.append({"key": "sharpe", "label": "Sharpe", "value": sharpe, "plain": sharpe_plain})

    return metrics


def _changes(current: Dict[str, Any], previous: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes: List[Dict[str, Any]] = []

    pv_d = round(_f(current, "portfolio_value") - _f(previous, "portfolio_value"), 2)
    pnl_d = round(_f(current, "pnl") - _f(previous, "pnl"), 2)
    vol_d = round(_f(current, "volatility") - _f(previous, "volatility"), 6)
    var_d = round(_f(current, "var") - _f(previous, "var"), 2)
    sharpe_c = _f(current, "sharpe")
    sharpe_p = _f(previous, "sharpe")

    if pv_d != 0:
        direction = "rose" if pv_d > 0 else "fell"
        changes.append({
            "key": "portfolio_value",
            "direction": "up" if pv_d > 0 else "down",
            "delta": pv_d,
            "plain": (
                f"Your portfolio value {direction} {_signed_money(pv_d)} since the "
                f"last update, so your P&L moved by the same amount "
                f"({_signed_money(pnl_d)}). This comes from a trade you placed or a "
                f"market price move in your existing holdings."
            ),
        })

    if vol_d != 0:
        if vol_d > 0:
            plain = (
                f"Volatility increased (+{_pct(vol_d)}), meaning your portfolio has "
                f"been swinging a bit more. That's why VaR rose too — VaR is directly "
                f"proportional to volatility."
            )
        else:
            plain = (
                f"Volatility eased ({_pct(vol_d)}), so your portfolio has been "
                f"steadier and your estimated daily risk (VaR) came down with it."
            )
        changes.append({
            "key": "volatility",
            "direction": "up" if vol_d > 0 else "down",
            "delta": vol_d,
            "plain": plain,
        })
    elif var_d != 0:
        # Volatility flat but VaR moved -> driven by portfolio size.
        direction = "rose" if var_d > 0 else "fell"
        changes.append({
            "key": "var",
            "direction": "up" if var_d > 0 else "down",
            "delta": var_d,
            "plain": (
                f"Your VaR {direction} {_signed_money(var_d)} mainly because your "
                f"portfolio size changed — VaR scales with portfolio value even when "
                f"volatility holds steady."
            ),
        })

    if (sharpe_c >= 0) != (sharpe_p >= 0):
        if sharpe_c >= 0:
            plain = (
                "Your Sharpe ratio flipped positive: recent risk-adjusted return "
                "improved."
            )
        else:
            plain = (
                "Your Sharpe ratio turned negative: over the recent window your "
                "portfolio drifted down on average. It's a short-window measure and "
                "can flip back quickly."
            )
        changes.append({
            "key": "sharpe",
            "direction": "up" if sharpe_c >= sharpe_p else "down",
            "delta": round(sharpe_c - sharpe_p, 4),
            "plain": plain,
        })

    return changes


def _headline(snapshot: Dict[str, Any]) -> str:
    pv = _f(snapshot, "portfolio_value")
    pnl = _f(snapshot, "pnl")
    seed = round(pv - pnl, 2)
    pnl_pct = (pnl / seed) if seed else 0.0
    if pnl > 0:
        return f"Your portfolio is worth {_money(pv)} — up {_money(pnl)} ({_pct(pnl_pct, 1)})."
    if pnl < 0:
        return f"Your portfolio is worth {_money(pv)} — down {_money(abs(pnl))} ({_pct(pnl_pct, 1)})."
    return f"Your portfolio is worth {_money(pv)} — flat versus your starting cash."


def _notes(snapshot: Dict[str, Any]) -> List[str]:
    notes = [
        "These figures update live as you trade and as market prices move.",
        (
            f"VaR here is parametric (about {int(VAR_CONFIDENCE * 100)}% confidence, "
            f"{VAR_HORIZON_DAYS}-day horizon). Volatility and Sharpe use a short "
            f"rolling window, so they react quickly and can swing."
        ),
    ]
    if _f(snapshot, "volatility") <= 0 or _f(snapshot, "var") <= 0:
        notes.append(
            "Volatility, VaR and Sharpe read 0 until enough live price history has "
            "accrued — this is 'not enough data yet', not 'no risk'."
        )
    return notes


def explain_snapshot(current: Dict[str, Any],
                     previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build a plain-language analysis of a risk snapshot.

    :param current: the latest snapshot (RiskSummary / RiskComputed ``data`` shape).
    :param previous: an optional earlier snapshot; when supplied, a "what changed
        and why" section is included.
    :returns: a JSON-serializable dict: headline, summary, metrics, changes, notes.
    """
    metrics = _metrics(current)
    changes = _changes(current, previous) if previous else []

    if changes:
        summary = "Here's what changed and why, in plain language."
    else:
        summary = "Here's what each number means for your account, in plain language."

    return {
        "account_id": current.get("account_id"),
        "computed_at": current.get("computed_at"),
        "headline": _headline(current),
        "summary": summary,
        "metrics": metrics,
        "changes": changes,
        "notes": _notes(current),
    }
