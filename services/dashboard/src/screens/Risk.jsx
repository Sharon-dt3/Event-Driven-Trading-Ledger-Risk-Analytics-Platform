import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useAsync } from '../hooks/useAsync';
import { useStreamData } from '../stream/StreamContext';
import { StateBlock } from '../components/StateBlock';
import { fmtMoney, fmtNum, fmtPct, fmtTime } from '../format';
import { buildRiskNarrative } from '../explain';

function Metric({ label, value, sub }) {
  return (
    <div className="card">
      <div className="card__title">{label}</div>
      <div className="card__value">{value}</div>
      {sub && <div className="card__meta">{sub}</div>}
    </div>
  );
}

function Explainability({ narrative, isLive, aiAvailable, aiOn, onToggleAi, aiLoading, aiError }) {
  if (!narrative) return null;
  const isAi = narrative.mode === 'llm';
  return (
    <div className="panel explain">
      <div className="section-head">
        <h3>What this means</h3>
        <div className="explain__badges">
          {isAi ? (
            <span className="pill pill--ai">AI explanation</span>
          ) : (
            <span className="muted">{isLive ? 'live analysis' : 'analysis'}</span>
          )}
          {aiAvailable && (
            <label className="field field--inline explain__toggle">
              <input type="checkbox" checked={aiOn} onChange={(e) => onToggleAi(e.target.checked)} />
              <span>{aiLoading ? 'Generating AI…' : 'AI explanation'}</span>
            </label>
          )}
        </div>
      </div>

      {aiError && (
        <p className="muted">AI explanation unavailable right now — showing the standard analysis.</p>
      )}

      <p className="explain__headline">{narrative.headline}</p>
      <p className="muted">{narrative.summary}</p>

      {narrative.changes.length > 0 && (
        <div className="explain__changes">
          <h4>What just changed &amp; why</h4>
          <ul>
            {narrative.changes.map((c, i) => (
              <li key={`chg-${c.key}-${i}`} className={`explain__change explain__change--${c.direction}`}>
                {c.plain}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="explain__metrics">
        <h4>Your numbers, explained</h4>
        <dl>
          {narrative.metrics.map((m) => (
            <div key={`m-${m.key}`} className="explain__metric">
              <dt>{m.label}</dt>
              <dd>{m.plain}</dd>
            </div>
          ))}
        </dl>
      </div>

      {narrative.notes.length > 0 && (
        <ul className="explain__notes muted">
          {narrative.notes.map((n, i) => (
            <li key={`note-${i}`}>{n}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Risk() {
  const { account } = useAuth();
  const { risk: liveRisk, riskLog } = useStreamData();

  const summary = useAsync(() => api.riskSummary(account), [account]);
  const varDetail = useAsync(() => api.riskVar(account, 'parametric'), [account]);

  // Optional grounded AI explanation: only offered when the server advertises it.
  const [aiAvailable, setAiAvailable] = useState(false);
  const [aiOn, setAiOn] = useState(false);
  const [aiNarrative, setAiNarrative] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .riskExplainCapabilities()
      .then((c) => {
        if (!cancelled) setAiAvailable(!!(c && c.llm_enabled));
      })
      .catch(() => {
        if (!cancelled) setAiAvailable(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Prefer the live SSE snapshot when it matches the selected account; fall back
  // to the REST summary (fetch-on-load, coherent with the last published event).
  const live = liveRisk && liveRisk.account_id === account ? liveRisk : null;
  const s = live || summary.data;

  // VaR detail prefers the live SSE snapshot so its VaR value and timestamp
  // always match the summary card above. The live risk.updates event doesn't
  // carry confidence/horizon, so those come from the REST detail when present,
  // else the documented parametric defaults (95% confidence, 1-day horizon).
  const varView = live
    ? {
        var: live.var,
        var_method: live.var_method,
        confidence: varDetail.data?.confidence ?? 0.95,
        horizon_days: varDetail.data?.horizon_days ?? 1,
        computed_at: live.computed_at,
      }
    : varDetail.data;

  // For the live "what changed and why" narrative, diff the two most recent
  // risk.updates events for this account (riskLog is most-recent-first).
  const accountLog = (riskLog || []).filter((r) => r.account_id === account);
  const previous = live && accountLog.length > 1 ? accountLog[1] : null;
  const ruleNarrative = s ? buildRiskNarrative(s, previous) : null;

  // Fetch the grounded AI rewrite on demand (and refresh it as the snapshot
  // changes while the toggle is on). Falls back silently to the rule-based text.
  useEffect(() => {
    if (!aiOn || !s) {
      setAiNarrative(null);
      return undefined;
    }
    let cancelled = false;
    setAiLoading(true);
    setAiError(false);
    api
      .riskExplain(account, 'llm')
      .then((data) => {
        if (cancelled) return;
        if (data && data.mode === 'llm') setAiNarrative(data);
        else {
          setAiNarrative(null);
          setAiError(true);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAiNarrative(null);
          setAiError(true);
        }
      })
      .finally(() => {
        if (!cancelled) setAiLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // Re-run when the account changes or a new snapshot arrives.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiOn, account, s && s.computed_at]);

  const narrative = aiOn && aiNarrative ? aiNarrative : ruleNarrative;

  const refresh = () => {
    summary.run().catch(() => {});
    varDetail.run().catch(() => {});
  };

  const noData = !live && !summary.loading && (summary.error?.status === 404 || !summary.data);

  return (
    <section>
      <div className="section-head">
        <h2>Risk metrics</h2>
        <button className="btn btn--ghost" onClick={refresh}>
          Refresh
        </button>
      </div>
      <p className="muted">
        Account <code>{account}</code>
        {live ? ' · live from risk.updates' : ' · latest published snapshot'}
      </p>

      <StateBlock
        loading={summary.loading && !live}
        error={live ? null : summary.error?.status && summary.error.status !== 404 ? summary.error : null}
        empty={noData}
        emptyText="No metrics computed yet — post a trade or wait for a price move."
      >
        {s && (
          <>
            <div className="cards">
              <Metric label="Portfolio value" value={fmtMoney(s.portfolio_value)} />
              <Metric label="P&L" value={fmtMoney(s.pnl)} />
              <Metric label="Volatility" value={fmtPct(s.volatility)} />
              <Metric
                label="VaR"
                value={fmtMoney(s.var)}
                sub={s.var_method ? `${s.var_method}` : undefined}
              />
              <Metric label="Sharpe" value={fmtNum(s.sharpe, 2)} />
            </div>
            <p className="muted">Computed at {fmtTime(s.computed_at)}</p>

            <Explainability
              narrative={narrative}
              isLive={!!live}
              aiAvailable={aiAvailable}
              aiOn={aiOn}
              onToggleAi={setAiOn}
              aiLoading={aiLoading}
              aiError={aiError}
            />
          </>
        )}

        <h3>VaR detail</h3>
        <StateBlock
          loading={varDetail.loading && !live}
          error={varDetail.error?.status && varDetail.error.status !== 404 ? varDetail.error : null}
          empty={!varView}
          emptyText="No VaR detail yet."
        >
          {varView && (
            <table className="table table--kv">
              <tbody>
                <tr>
                  <th>VaR</th>
                  <td>{fmtMoney(varView.var)}</td>
                </tr>
                <tr>
                  <th>Method</th>
                  <td>{varView.var_method}</td>
                </tr>
                <tr>
                  <th>Confidence</th>
                  <td>{fmtPct(varView.confidence)}</td>
                </tr>
                <tr>
                  <th>Horizon</th>
                  <td>{varView.horizon_days} day(s)</td>
                </tr>
                <tr>
                  <th>Computed at</th>
                  <td>{fmtTime(varView.computed_at)}</td>
                </tr>
              </tbody>
            </table>
          )}
        </StateBlock>
      </StateBlock>
    </section>
  );
}
