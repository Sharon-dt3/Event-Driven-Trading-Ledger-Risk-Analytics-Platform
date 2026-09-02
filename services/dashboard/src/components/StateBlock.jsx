// Renders standard loading / error / empty states, or the children when data
// is present. Keeps every screen's empty/loading/error handling consistent.
export function StateBlock({ loading, error, empty, emptyText = 'No data yet.', children }) {
  if (loading) {
    return <div className="state state--loading">Loading…</div>;
  }
  if (error) {
    return (
      <div className="state state--error">
        <strong>Something went wrong.</strong>
        <div className="state__detail">{error.message}</div>
      </div>
    );
  }
  if (empty) {
    return <div className="state state--empty">{emptyText}</div>;
  }
  return children;
}
