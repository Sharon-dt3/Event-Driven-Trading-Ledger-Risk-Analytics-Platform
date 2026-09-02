// REST client for the TradePulse Ledger and Risk APIs.
//
// Base paths mirror the frozen OpenAPI contracts and the dev/prod proxies:
//   - Ledger: '/ledger' (proxy strips the prefix)   -> /auth, /trades, ...
//   - Risk:   '/risk/...' served literally
// The JWT from login is attached as a Bearer token on authenticated calls.

const LEDGER_BASE = '/ledger';
const TOKEN_KEY = 'tp_token';
const USER_KEY = 'tp_user';

function authHeaders() {
  const token = localStorage.getItem(TOKEN_KEY);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// A stored JWT can be expired or otherwise rejected by ledger-core (HTTP 401),
// which previously left the app "logged in" while every authenticated call
// failed (Trades/Positions/Risk/Audit all 401). Recover automatically: drop the
// stale credentials and send the user to the login screen so they can re-auth.
// Guarded so it only fires in a browser and never loops on the login request.
function handleUnauthorized() {
  try {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  } catch {
    // localStorage may be unavailable (e.g. privacy mode); ignore.
  }
  if (typeof window !== 'undefined' && window.location.pathname !== '/login') {
    window.location.assign('/login');
  }
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

  // Authenticated request rejected by the token check: clear + redirect to login
  // (unless the caller explicitly tolerates this status).
  if (res.status === 401 && auth && !okStatuses.includes(401)) {
    handleUnauthorized();
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
