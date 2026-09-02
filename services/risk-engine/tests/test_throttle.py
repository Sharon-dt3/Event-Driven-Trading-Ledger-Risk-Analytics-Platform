"""Step 4: 2B throttle behavior (the control-loop proof, distinct from the
metric math). Proves the failure mode we care about is prevented: a burst of
ticks must NOT publish one RiskComputed per tick — exactly one per interval —
and the throttle fires from price movement alone (no new trade required).
"""
import os
import tempfile

from app.config import Config
from app.consumer import RiskConsumer
from app.store import RiskStore
from app.worker import RiskWorker


class FakeRedis:
    """Minimal stand-in capturing published stream entries (xadd only)."""

    def __init__(self):
        self.added = []

    def xadd(self, stream, fields):
        self.added.append((stream, fields))
        return "0-1"


def _seed_account(store, symbol="AAPL", qty=10, price=100.0):
    # One applied ledger event so the account exists with a position to value.
    store.apply_ledger_event(
        event_id="e1", account_id="acct", symbol=symbol, side="BUY",
        quantity=qty, price=price, cash_delta=-(qty * price),
        position_after=qty, correlation_id="c1", posted_at="t")


def _worker(tmp, **cfg_over):
    db = os.path.join(tmp, "risk_state.db")
    store = RiskStore(db)
    _seed_account(store)
    cfg = Config(db_path=db, recompute_interval_ms=1000, window_size=30, **cfg_over)
    return RiskWorker(FakeRedis(), RiskConsumer(store, cfg), cfg), store


def test_burst_yields_one_recompute_per_interval():
    with tempfile.TemporaryDirectory() as tmp:
        w, _ = _worker(tmp)
        published = w.maybe_recompute(now=100.0)      # first call -> fires
        for i in range(99):                            # burst within 1s -> none
            published += w.maybe_recompute(now=100.0 + 0.001 * i)
        assert published == 1
        assert len(w.r.added) == 1                     # exactly one publish
        # After the interval elapses -> fires again.
        assert w.maybe_recompute(now=101.5) == 1
        assert len(w.r.added) == 2


def test_throttle_fires_from_price_movement_without_new_trade():
    with tempfile.TemporaryDirectory() as tmp:
        w, store = _worker(tmp)
        # No new ledger events; only marks change -> PV changes -> recompute.
        marks = [100.0, 110.0, 99.9]  # PV: 10000, 10100, 9999
        for i, mk in enumerate(marks):
            store.upsert_price("AAPL", mk)
            w.maybe_recompute(now=1000.0 + i * 2.0)  # 2s apart > 1s interval
        assert len(w.r.added) == 3                   # one per interval, no trades
        # PV series [10000, 10100, 9999] -> returns [0.01, -0.01] -> vol 0.01.
        assert store.pv_returns("acct")[0] == 0.01
        assert store.pv_window("acct") == [10000.0, 10100.0, 9999.0]
