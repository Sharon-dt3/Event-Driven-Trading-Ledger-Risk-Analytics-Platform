import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useAsync } from '../hooks/useAsync';
import { StateBlock } from '../components/StateBlock';
import { fmtMoney, fmtNum } from '../format';

export function Positions() {
  const { account } = useAuth();

  const balances = useAsync(() => api.balances(account), [account]);
  const positions = useAsync(() => api.positions(account), [account]);

  const refresh = () => {
    balances.run().catch(() => {});
    positions.run().catch(() => {});
  };

  return (
    <section>
      <div className="section-head">
        <h2>Positions & balances</h2>
        <button className="btn btn--ghost" onClick={refresh}>
          Refresh
        </button>
      </div>
      <p className="muted">
        Account <code>{account}</code>
      </p>

      <h3>Cash balances</h3>
      <StateBlock
        loading={balances.loading}
        error={balances.error}
        empty={Array.isArray(balances.data) && balances.data.length === 0}
        emptyText="No balances for this account."
      >
        <table className="table">
          <thead>
            <tr>
              <th>Account</th>
              <th>Currency</th>
              <th className="num">Amount</th>
            </tr>
          </thead>
          <tbody>
            {(balances.data || []).map((b, i) => (
              <tr key={`${b.account_id}-${b.currency}-${i}`}>
                <td>{b.account_id}</td>
                <td>{b.currency}</td>
                <td className="num">{fmtMoney(b.amount)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </StateBlock>

      <h3>Positions</h3>
      <StateBlock
        loading={positions.loading}
        error={positions.error}
        empty={Array.isArray(positions.data) && positions.data.length === 0}
        emptyText="No open positions."
      >
        <table className="table">
          <thead>
            <tr>
              <th>Symbol</th>
              <th className="num">Quantity</th>
              <th className="num">Avg price</th>
            </tr>
          </thead>
          <tbody>
            {(positions.data || []).map((p, i) => (
              <tr key={`${p.symbol}-${i}`}>
                <td>{p.symbol}</td>
                <td className="num">{fmtNum(p.quantity, 4)}</td>
                <td className="num">{fmtMoney(p.avg_price)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </StateBlock>
    </section>
  );
}
