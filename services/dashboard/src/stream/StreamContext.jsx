import { createContext, useContext, useEffect, useState } from 'react';

const StreamContext = createContext(null);

// Maintains ONE EventSource to the gateway /stream feed and exposes the latest
// tick per symbol, a rolling tick log, the latest risk snapshot, a rolling risk
// log, and the connection status. EventSource auto-reconnects on transient
// errors, so screens simply read the live values.
export function StreamProvider({ children }) {
  const [status, setStatus] = useState('connecting');
  const [ticks, setTicks] = useState({}); // symbol -> latest tick
  const [tickLog, setTickLog] = useState([]); // most-recent-first
  const [risk, setRisk] = useState(null); // latest RiskComputed data
  const [riskLog, setRiskLog] = useState([]);

  useEffect(() => {
    const es = new EventSource('/stream');

    es.onopen = () => setStatus('open');
    es.onerror = () => setStatus('reconnecting');

    es.addEventListener('ticks', (e) => {
      try {
        const env = JSON.parse(e.data);
        const d = env.data || {};
        if (!d.symbol) return;
        const entry = {
          symbol: d.symbol,
          price: d.price,
          volume: d.volume,
          tick_time: d.tick_time,
          at: Date.now(),
        };
        setStatus('open');
        setTicks((prev) => ({ ...prev, [d.symbol]: entry }));
        setTickLog((prev) => [entry, ...prev].slice(0, 50));
      } catch {
        /* ignore malformed frame */
      }
    });

    es.addEventListener('risk', (e) => {
      try {
        const env = JSON.parse(e.data);
        const d = env.data || {};
        setStatus('open');
        setRisk(d);
        setRiskLog((prev) => [{ ...d, at: Date.now() }, ...prev].slice(0, 50));
      } catch {
        /* ignore malformed frame */
      }
    });

    return () => es.close();
  }, []);

  return (
    <StreamContext.Provider value={{ status, ticks, tickLog, risk, riskLog }}>
      {children}
    </StreamContext.Provider>
  );
}

export function useStreamData() {
  const ctx = useContext(StreamContext);
  if (!ctx) throw new Error('useStreamData must be used within StreamProvider');
  return ctx;
}
