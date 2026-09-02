export const fmtMoney = (n) =>
  n == null || Number.isNaN(Number(n))
    ? '—'
    : Number(n).toLocaleString(undefined, { style: 'currency', currency: 'USD' });

export const fmtNum = (n, d = 2) =>
  n == null || Number.isNaN(Number(n)) ? '—' : Number(n).toFixed(d);

export const fmtPct = (n, d = 2) =>
  n == null || Number.isNaN(Number(n)) ? '—' : `${(Number(n) * 100).toFixed(d)}%`;

export const fmtTime = (t) => {
  if (!t) return '—';
  const d = new Date(t);
  return Number.isNaN(d.getTime()) ? String(t) : d.toLocaleTimeString();
};
