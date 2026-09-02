import { useCallback, useEffect, useState } from 'react';

// Runs an async function and tracks {loading, error, data}. Re-runs when `deps`
// change (unless immediate=false). `run` can also be invoked manually (e.g. to
// refresh after a mutation).
export function useAsync(fn, deps = [], { immediate = true } = {}) {
  const [state, setState] = useState({ loading: immediate, error: null, data: null });

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const run = useCallback(async (...args) => {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await fn(...args);
      setState({ loading: false, error: null, data });
      return data;
    } catch (error) {
      setState({ loading: false, error, data: null });
      throw error;
    }
  }, deps);

  useEffect(() => {
    if (immediate) run().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { ...state, run };
}
