import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev proxy targets (override with env when running services on other hosts).
const LEDGER = process.env.LEDGER_URL || 'http://localhost:8082';
const RISK = process.env.RISK_URL || 'http://localhost:8083';
const GATEWAY = process.env.GATEWAY_URL || 'http://localhost:8084';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 3000,
    proxy: {
      // Ledger service serves /auth, /trades, /balances, /positions, /audit
      // (no /ledger prefix), so strip the ALB-style /ledger base path here.
      '/ledger': {
        target: LEDGER,
        changeOrigin: true,
        rewrite: (p) => p.replace(/^\/ledger/, ''),
      },
      // Risk service serves /risk/summary and /risk/var literally — no rewrite.
      '/risk': { target: RISK, changeOrigin: true },
      // Gateway SSE feed.
      '/stream': { target: GATEWAY, changeOrigin: true },
    },
  },
  preview: { host: true, port: 3000 },
});
