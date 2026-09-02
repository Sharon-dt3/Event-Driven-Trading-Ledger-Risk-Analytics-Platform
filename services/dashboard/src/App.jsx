const SERVICES = [
  { name: 'Ledger Core', url: 'http://localhost:8082/actuator/health' },
  { name: 'Risk Engine', url: 'http://localhost:8083/health' },
  { name: 'Market Data', url: 'http://localhost:8081/health' },
  { name: 'Gateway', url: 'http://localhost:8084/health' },
];

export default function App() {
  return (
    <main style={{ fontFamily: 'system-ui, sans-serif', padding: '2rem', maxWidth: 720, margin: '0 auto' }}>
      <h1>TradePulse Dashboard</h1>
      <p>Phase 1 skeleton — the live trading UI is delivered in later phases.</p>
      <h2>Backend services</h2>
      <ul>
        {SERVICES.map((s) => (
          <li key={s.name}>
            {s.name}: <a href={s.url} target="_blank" rel="noreferrer">{s.url}</a>
          </li>
        ))}
      </ul>
    </main>
  );
}
