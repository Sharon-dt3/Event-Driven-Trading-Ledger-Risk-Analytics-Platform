import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';

// Demo logins are a development-only convenience. They are gated behind
// Vite's `import.meta.env.DEV` flag so that the credentials are NOT rendered
// in the UI and NOT included in the production build that nginx serves.
// Never rely on these for anything other than local development.
const DEMO = import.meta.env.DEV
  ? [
      { username: 'demo_trader', password: 'trader-pw', role: 'trader' },
      { username: 'viewer', password: 'viewer-pw', role: 'viewer' },
      { username: 'compliance', password: 'compliance-pw', role: 'compliance' },
      { username: 'admin', password: 'admin-pw', role: 'admin' },
    ]
  : [];

export function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = location.state?.from?.pathname || '/';

  // Do not pre-fill real credentials in production. In dev, prefill the
  // lowest-privilege trader account only as a convenience.
  const [username, setUsername] = useState(import.meta.env.DEV ? 'demo_trader' : '');
  const [password, setPassword] = useState(import.meta.env.DEV ? 'trader-pw' : '');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const onSubmit = async (e) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(username, password);
      navigate(from, { replace: true });
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="login">
      <form className="login__card" onSubmit={onSubmit}>
        <h1 className="login__brand">TradePulse</h1>
        <p className="login__sub">Sign in to the trading dashboard</p>

        <label className="field">
          <span>Username</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </label>

        {error && <div className="state state--error">{error.message}</div>}

        <button className="btn btn--primary" type="submit" disabled={loading}>
          {loading ? 'Signing in…' : 'Sign in'}
        </button>

        {DEMO.length > 0 && (
          <div className="login__demo">
            <span>Demo logins (dev only):</span>
            <ul>
              {DEMO.map((d) => (
                <li key={d.username}>
                  <button
                    type="button"
                    className="linkbtn"
                    onClick={() => {
                      setUsername(d.username);
                      setPassword(d.password);
                    }}
                  >
                    {d.username}
                  </button>
                  <em>{d.role}</em>
                </li>
              ))}
            </ul>
          </div>
        )}
      </form>
    </div>
  );
}
