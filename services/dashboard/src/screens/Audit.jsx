import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { useAsync } from '../hooks/useAsync';
import { StateBlock } from '../components/StateBlock';
import { fmtTime } from '../format';

export function Audit() {
  const { account, user } = useAuth();
  const audit = useAsync(() => api.audit(account), [account]);

  const forbidden = audit.error?.status === 403;

  return (
    <section>
      <div className="section-head">
        <h2>Audit trail</h2>
        <button className="btn btn--ghost" onClick={() => audit.run().catch(() => {})}>
          Refresh
        </button>
      </div>
      <p className="muted">
        Immutable compliance log for <code>{account}</code>. Requires the{' '}
        <strong>compliance</strong> or <strong>admin</strong> role (you are{' '}
        <strong>{user?.role}</strong>).
      </p>

      {forbidden ? (
        <div className="state state--error">
          Your role (<strong>{user?.role}</strong>) is not permitted to view the audit log.
          Sign in as <code>compliance</code> or <code>admin</code>.
        </div>
      ) : (
        <StateBlock
          loading={audit.loading}
          error={audit.error}
          empty={Array.isArray(audit.data) && audit.data.length === 0}
          emptyText="No audit entries."
        >
          <table className="table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Action</th>
                <th>Outcome</th>
                <th>Reason</th>
                <th>Audit ID</th>
              </tr>
            </thead>
            <tbody>
              {(audit.data || []).map((a, i) => (
                <tr key={`${a.audit_id}-${i}`}>
                  <td>{fmtTime(a.recorded_at)}</td>
                  <td>{a.action}</td>
                  <td>
                    <span className={`pill pill--${a.outcome}`}>{a.outcome}</span>
                  </td>
                  <td>{a.reason || '—'}</td>
                  <td className="mono">{a.audit_id}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </StateBlock>
      )}
    </section>
  );
}
