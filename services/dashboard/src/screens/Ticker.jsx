import { useStreamData } from '../stream/StreamContext';
import { StateBlock } from '../components/StateBlock';
import { fmtMoney, fmtNum, fmtTime } from '../format';

export function Ticker() {
  const { status, ticks, tickLog } = useStreamData();
  const symbols = Object.values(ticks).sort((a, b) => a.symbol.localeCompare(b.symbol));

  return (
    <section>
      <h2>Live ticker</h2>
      <p className="muted">
        Streaming <code>market.ticks</code> via the gateway SSE feed — feed is{' '}
        <strong>{status}</strong>.
      </p>

      <StateBlock
        loading={status === 'connecting' && symbols.length === 0}
        empty={symbols.length === 0}
        emptyText="Waiting for the first tick… (start market-data + gateway)"
      >
        <div className="cards">
          {symbols.map((t) => (
            <div className="card" key={t.symbol}>
              <div className="card__title">{t.symbol}</div>
              <div className="card__value">{fmtMoney(t.price)}</div>
              <div className="card__meta">
                vol {fmtNum(t.volume, 0)} · {fmtTime(t.tick_time)}
              </div>
            </div>
          ))}
        </div>

        <h3>Recent ticks</h3>
        <table className="table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Symbol</th>
              <th className="num">Price</th>
              <th className="num">Volume</th>
            </tr>
          </thead>
          <tbody>
            {tickLog.map((t, i) => (
              <tr key={`${t.symbol}-${t.at}-${i}`}>
                <td>{fmtTime(t.tick_time)}</td>
                <td>{t.symbol}</td>
                <td className="num">{fmtMoney(t.price)}</td>
                <td className="num">{fmtNum(t.volume, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </StateBlock>
    </section>
  );
}
