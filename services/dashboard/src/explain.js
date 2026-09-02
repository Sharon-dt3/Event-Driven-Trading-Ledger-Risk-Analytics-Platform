// Risk explainability (pure, client-side).
//
// Turns risk snapshots into plain-language analysis for users without financial
// expertise. When a `previous` snapshot is supplied (the prior risk.updates
// event), it also explains *what changed and why* — e.g. that VaR rose because
// volatility increased, since VaR is proportional to volatility x portfolio
// value. This mirrors the backend app/explain.py so REST and live views agree.
//
// Additive only: does not depend on or change the frozen RiskComputed/RiskSummary
// shapes beyond reading their documented fields.

import { fmtMoney, fmtPct, fmtNum } from './format';

const VAR_CONFIDENCE = 0.95;
const VAR_HORIZON_DAYS = 1;

const VOL_VERY_LOW = 0.001;
const VOL_LOW = 0.005;
const VOL_MODERATE = 0.02;

const num = (v, d = 0) => (v == null || Number.isNaN(Number(v)) ? d : Number(v));

const signedMoney = (x) => `${x >= 0 ? '+' : '-'}${fmtMoney(Math.abs(x))}`;
const signedPct = (x) => `${x >= 0 ? '+' : ''}${fmtPct(x)}`;

function volBand(vol) {
  if (vol <= 0) return 'not measurable yet';
  if (vol < VOL_VERY_LOW) return 'very calm';
  if (vol < VOL_LOW) return 'low';
  if (vol < VOL_MODERATE) return 'moderate';
  return 'elevated';
}

function sharpeBand(sharpe, vol) {
  if (vol <= 0) return 'not measurable yet';
  if (sharpe >= 1) return 'strong';
  if (sharpe > 0) return 'modestly positive';
  if (sharpe === 0) return 'flat';
  return 'negative';
}

function headline(s) {
  const pv = num(s.portfolio_value);
  const pnl = num(s.pnl);
  const seed = pv - pnl;
  const pnlPct = seed ? pnl / seed : 0;
  if (pnl > 0) return `Your portfolio is worth ${fmtMoney(pv)} — up ${fmtMoney(pnl)} (${fmtPct(pnlPct)}).`;
  if (pnl < 0)
    return `Your portfolio is worth ${fmtMoney(pv)} — down ${fmtMoney(Math.abs(pnl))} (${fmtPct(pnlPct)}).`;
  return `Your portfolio is worth ${fmtMoney(pv)} — flat versus your starting cash.`;
}

function metrics(s) {
  const pv = num(s.portfolio_value);
  const pnl = num(s.pnl);
  const vol = num(s.volatility);
  const varv = num(s.var);
  const sharpe = num(s.sharpe);
  const seed = pv - pnl;
  const pnlPct = seed ? pnl / seed : 0;
  const varPct = pv ? varv / pv : 0;

  const out = [];

  out.push({
    key: 'portfolio_value',
    label: 'Portfolio value',
    plain:
      `This is what your account is worth right now — your cash plus the market ` +
      `value of your holdings priced at the latest ticks. It currently stands at ${fmtMoney(pv)}.`,
  });

  out.push({
    key: 'pnl',
    label: 'P&L',
    plain:
      pnl >= 0
        ? `You're up ${fmtMoney(pnl)} (${fmtPct(pnlPct)}) versus your starting cash of ${fmtMoney(
            seed,
          )}. This is an on-paper (unrealized) gain — it moves with prices and isn't locked in until you sell.`
        : `You're down ${fmtMoney(Math.abs(pnl))} (${fmtPct(pnlPct)}) versus your starting cash of ${fmtMoney(
            seed,
          )}. This is an on-paper (unrealized) loss and recovers if prices rebound.`,
  });

  out.push({
    key: 'volatility',
    label: 'Volatility',
    plain:
      vol <= 0
        ? `Volatility measures how much your portfolio value bounces between updates. There isn't enough price history yet to measure it — it fills in shortly.`
        : `Volatility measures how much your portfolio value swings between updates. At ${fmtPct(
            vol,
          )} it's currently ${volBand(vol)} — a higher number means bigger swings both up and down.`,
  });

  out.push({
    key: 'var',
    label: 'VaR',
    plain:
      varv <= 0
        ? `Value at Risk (VaR) estimates your likely worst-case loss on a normal day. Not enough history yet to compute it.`
        : `Value at Risk (VaR) estimates your downside on a normal day. With about ${Math.round(
            VAR_CONFIDENCE * 100,
          )}% confidence, you wouldn't expect to lose more than ${fmtMoney(
            varv,
          )} over ${VAR_HORIZON_DAYS} trading day — roughly ${fmtPct(
            varPct,
          )} of your portfolio. It rises when either your volatility or portfolio size grows.`,
  });

  out.push({
    key: 'sharpe',
    label: 'Sharpe',
    plain:
      vol <= 0
        ? `The Sharpe ratio compares recent return against how bumpy the ride was. Not enough history yet to compute it.`
        : sharpe < 0
        ? `The Sharpe ratio (${fmtNum(sharpe, 2)}) is your recent return per unit of risk. It's ${sharpeBand(
            sharpe,
            vol,
          )}: over the recent window your portfolio drifted down on average. It's a short-window figure that flips easily and doesn't contradict a positive overall P&L.`
        : `The Sharpe ratio (${fmtNum(sharpe, 2)}) is your recent return per unit of risk — it's ${sharpeBand(
            sharpe,
            vol,
          )}. Higher is better; it rewards steady gains and penalizes big swings.`,
  });

  return out;
}

function changes(cur, prev) {
  const out = [];
  const pvD = num(cur.portfolio_value) - num(prev.portfolio_value);
  const pnlD = num(cur.pnl) - num(prev.pnl);
  const volD = num(cur.volatility) - num(prev.volatility);
  const varD = num(cur.var) - num(prev.var);
  const sharpeC = num(cur.sharpe);
  const sharpeP = num(prev.sharpe);

  const roundEq = (a, b, eps) => Math.abs(a - b) < eps;

  if (!roundEq(pvD, 0, 0.005)) {
    out.push({
      key: 'portfolio_value',
      direction: pvD > 0 ? 'up' : 'down',
      plain:
        `Your portfolio value ${pvD > 0 ? 'rose' : 'fell'} ${signedMoney(pvD)} since the last update, ` +
        `so your P&L moved by the same amount (${signedMoney(pnlD)}). This comes from a trade you placed ` +
        `or a market price move in your holdings.`,
    });
  }

  if (!roundEq(volD, 0, 1e-6)) {
    out.push({
      key: 'volatility',
      direction: volD > 0 ? 'up' : 'down',
      plain:
        volD > 0
          ? `Volatility increased (${signedPct(volD)}), meaning your portfolio has been swinging a bit more. That's why VaR rose too — VaR is directly proportional to volatility.`
          : `Volatility eased (${signedPct(volD)}), so your portfolio has been steadier and your estimated daily risk (VaR) came down with it.`,
    });
  } else if (!roundEq(varD, 0, 0.005)) {
    out.push({
      key: 'var',
      direction: varD > 0 ? 'up' : 'down',
      plain: `Your VaR ${varD > 0 ? 'rose' : 'fell'} ${signedMoney(
        varD,
      )} mainly because your portfolio size changed — VaR scales with portfolio value even when volatility holds steady.`,
    });
  }

  if (sharpeC >= 0 !== sharpeP >= 0) {
    out.push({
      key: 'sharpe',
      direction: sharpeC >= sharpeP ? 'up' : 'down',
      plain:
        sharpeC >= 0
          ? `Your Sharpe ratio flipped positive: recent risk-adjusted return improved.`
          : `Your Sharpe ratio turned negative: over the recent window your portfolio drifted down on average. It's a short-window measure and can flip back quickly.`,
    });
  }

  return out;
}

function notes(s) {
  const n = [
    'These figures update live as you trade and as market prices move.',
    `VaR here is parametric (about ${Math.round(
      VAR_CONFIDENCE * 100,
    )}% confidence, ${VAR_HORIZON_DAYS}-day horizon). Volatility and Sharpe use a short rolling window, so they react quickly and can swing.`,
  ];
  if (num(s.volatility) <= 0 || num(s.var) <= 0) {
    n.push(
      "Volatility, VaR and Sharpe read 0 until enough live price history has accrued — that's 'not enough data yet', not 'no risk'.",
    );
  }
  return n;
}

// Build the full narrative. `previous` is optional (the prior risk snapshot);
// when present, a "what changed and why" section is included.
export function buildRiskNarrative(current, previous = null) {
  if (!current) return null;
  const chg = previous ? changes(current, previous) : [];
  return {
    account_id: current.account_id,
    computed_at: current.computed_at,
    headline: headline(current),
    summary: chg.length
      ? "Here's what changed and why, in plain language."
      : "Here's what each number means for your account, in plain language.",
    metrics: metrics(current),
    changes: chg,
    notes: notes(current),
  };
}
