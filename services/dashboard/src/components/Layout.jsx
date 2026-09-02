import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext';
import { useStreamData } from '../stream/StreamContext';

const NAV = [
  { to: '/', label: 'Ticker', end: true },
  { to: '/positions', label: 'Positions' },
  { to: '/trades', label: 'Trades' },
  { to: '/risk', label: 'Risk' },
  { to: '/audit', label: 'Audit' },
];

export function Layout() {
  const { user, account, setAccount, logout } = useAuth();
  const { status } = useStreamData();
  const navigate = useNavigate();

  const onLogout = () => {
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar__brand">TradePulse</div>
        <nav className="topbar__nav">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) => (isActive ? 'navlink navlink--active' : 'navlink')}
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="topbar__right">
          <span className={`conn conn--${status}`} title={`Live feed: ${status}`}>
            ● {status}
          </span>
          <label className="account">
            <span>Account</span>
            <input
              value={account}
              onChange={(e) => setAccount(e.target.value)}
              spellCheck={false}
            />
          </label>
          <span className="role">{user?.role}</span>
          <button className="btn btn--ghost" onClick={onLogout}>
            Log out
          </button>
        </div>
      </header>
      <main className="content">
        <Outlet />
      </main>
    </div>
  );
}
