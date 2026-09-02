import { useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useAsync } from '../hooks/useAsync';
import { StateBlock } from '../components/StateBlock';
import { fmtMoney, fmtNum, fmtTime } from '../format';

function uuid() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

const emptyForm = (account) => ({
  request_id: uuid(),
  account_id: account,
  symbol: 'AAPL',
  side: 'BUY',
  quantity: '10',
  price: '150',
});

export function Trades() {
  const { account } = useAuth();
  const [form, setForm] = useState(() => emptyForm(account));
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [submitError, setSubmitError] = useState(null);
  const [statusFilter, setStatusFilter] = useState('');

  const history = useAsync(() => api.trades(account, statusFilter || undefined), [
    account,
    statusFilter,
  ]);

  const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const onSubmit = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    setSubmitError(null);
    setResult(null);
    try {
      const res = await api.submitTrade({
        request_id: form.request_id,
        account_id: account,
        symbol: form.symbol.trim().toUpperCase(),
        side: form.side,
        quantity: Number(form.quantity),
        price: Number(form.price),
      });
      setResult(res);
      setForm(emptyForm(account)); // fresh request_id for the next submit
      history.run().catch(() => {});
    } catch (err) {
      setSubmitError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <section>
      <h2>Trades</h2>

      <form className="panel form-grid" onSubmit={onSubmit}>
        <label className="field">
          <span>Symbol</span>
          <input value={form.symbol} onChange={(e) => setField('symbol', e.target.value)} />
        </label>
        <label className="field">
          <span>Side</span>
          <select value={form.side} onChange={(e) => setField('side', e.target.value)}>
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </label>
        <label className="field">
          <span>Quantity</span>
          <input
            type="number"
            min="0"
            step="any"
            value={form.quantity}
            onChange={(e) => setField('quantity', e.target.value)}
          />
        </label>
        <label className="field">
          <span>Price</span>
          <input
            type="number"
            min="0"
            step="any"
            value={form.price}
            onChange={(e) => setField('price', e.target.value)}
          />
        </label>
        <div className="form-actions">
          <button className="btn btn--primary" type="submit" disabled={submitting}>
            {submitting ? 'Submitting…' : 'Submit trade'}
          </button>
        </div>
      </form>

      {submitError && <div className="state state--error">{submitError.message}</div>}
      {result && (
        <div
          className={`banner ${
            result.status === 'posted' ? 'banner--ok' : 'banner--warn'
          }`}
        >
          Trade <strong>{result.status}</strong>
          {result.status === 'rejected' && result.rejection_reason
            ? ` — ${result.rejection_reason}`
            : ''}
          {result.journal_entry_id ? ` (entry ${result.journal_entry_id})` : ''}
        </div>
      )}

      <div className="section-head">
        <h3>History</h3>
        <label className="field field--inline">
          <span>Status</span>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">all</option>
            <option value="posted">posted</option>
            <option value="rejected">rejected</option>
          </select>
        </label>
      </div>

      <StateBlock
        loading={history.loading}
        error={history.error}
        empty={Array.isArray(history.data) && history.data.length === 0}
        emptyText="No trades yet."
      >
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Symbol</th>
              <th>Side</th>
              <th className="num">Quantity</th>
              <th className="num">Price</th>
              <th>Status</th>
              <th>Reason</th>
              <th>Entry</th>
              <th>Request</th>
            </tr>
          </thead>
          <tbody>
            {(history.data || []).map((t, i) => (
              <tr key={`${t.request_id}-${i}`}>
                <td>{fmtTime(t.posted_at)}</td>
                <td>{t.symbol || '—'}</td>
                <td>
                  {t.side ? (
                    <span className={`pill pill--${t.side.toLowerCase()}`}>{t.side}</span>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="num">{t.quantity == null ? '—' : fmtNum(t.quantity, 4)}</td>
                <td className="num">{t.price == null ? '—' : fmtMoney(t.price)}</td>
                <td>
                  <span className={`pill pill--${t.status}`}>{t.status}</span>
                </td>
                <td>{t.rejection_reason || '—'}</td>
                <td>{t.journal_entry_id || '—'}</td>
                <td className="mono">{t.request_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </StateBlock>
    </section>
  );
}
