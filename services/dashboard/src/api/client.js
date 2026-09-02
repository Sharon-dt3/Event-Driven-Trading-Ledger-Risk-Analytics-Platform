// REST client for the TradePulse Ledger and Risk APIs.
//
// Base paths mirror the frozen OpenAPI contracts and the dev/prod proxies:
//   - Ledger: '/ledger' (proxy strips the prefix)   -> /auth, /trades, ...
//   - Risk:   '/risk/...' served literally
// The JWT from login is attached as a Bearer token on authenticated calls.

const LEDGER_BASE = '/ledger';
const TOKEN_KEY = 'tp_token';

function authHeaders() {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request(path, { method = 'GET', body, auth = true, okStatuses = [] } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(auth ? authHeaders() : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  const text = await res.text();
  let data = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }

  if (!res.ok && !okStatuses.includes(res.status)) {
    // Contract Error shape is {code, message}; fall back to other fields.
    const message =
      (data && (data.message || data.detail || data.error)) || `HTTP ${res.status}`;
    const err = new Error(message);
    err.status = res.status;
    err.body = data;
    throw err;
  }

  return data;
}

export const api = {
  login: (username, password) =>
    request(`${LEDGER_BASE}/auth/login`, {
      method: 'POST',
      body: { username, password },
      auth: false,
    }),

  balances: (accountId) =>
    request(`${LEDGER_BASE}/balances?account_id=${encodeURIComponent(accountId)}`),

  positions: (accountId) =>
    request(`${LEDGER_BASE}/positions?account_id=${encodeURIComponent(accountId)}`),

  trades: (accountId, status) => {
    const params = new URLSearchParams();
    if (accountId) params.set('account_id', accountId);
    if (status) params.set('status', status);
    const qs = params.toString();
    return request(`${LEDGER_BASE}/trades${qs ? `?${qs}` : ''}`);
  },

  // 201 (posted) and 409 (rejected) both return a TradeResult body; treat 409
  // as a valid business outcome rather than an error.
  submitTrade: (trade) =>
    request(`${LEDGER_BASE}/trades`, {
      method: 'POST',
      body: trade,
      okStatuses: [409],
    }),

  audit: (accountId) =>
    request(
      `${LEDGER_BASE}/audit${accountId ? `?account_id=${encodeURIComponent(accountId)}` : ''}`,
    ),

  riskSummary: (accountId) =>
    request(`/risk/summary?account_id=${encodeURIComponent(accountId)}`),

  riskVar: (accountId, method) => {
    const params = new URLSearchParams({ account_id: accountId });
    if (method) params.set('method', method);
    return request(`/risk/var?${params.toString()}`);
  },

  // Explainability: deterministic by default; pass mode='llm' for the optional
  // grounded AI rewrite (server falls back to rule-based text if unavailable).
  riskExplain: (accountId, mode) => {
    const params = new URLSearchParams({ account_id: accountId });
    if (mode) params.set('mode', mode);
    return request(`/risk/explain?${params.toString()}`);
  },

  // Whether the optional grounded LLM explanation mode is enabled server-side.
  riskExplainCapabilities: () => request(`/risk/explain/capabilities`),
};
