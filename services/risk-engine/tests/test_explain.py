"""Tests for the risk explainability layer (app/explain.py) and /risk/explain.

Offline (no Redis). Cover: level-based narrative for a fresh snapshot, the
"what changed and why" section when a previous snapshot is supplied, the
window-still-filling caveat when volatility/VaR are 0, and the REST endpoint's
200/404 behavior against the shared store.
"""
from fastapi.testclient import TestClient

from app.explain import explain_snapshot
from app.main import app
from app.store import RiskStore

client = TestClient(app)


def _snap(pv=15000.0, pnl=5000.0, vol=0.004, var=99.0, sharpe=0.3,
          account_id="acct_123", computed_at="2026-01-01T00:00:00+00:00"):
    return {
        "account_id": account_id,
        "portfolio_value": pv,
        "pnl": pnl,
        "volatility": vol,
        "var": var,
        "var_method": "parametric",
        "sharpe": sharpe,
        "computed_at": computed_at,
    }


def test_explain_levels_has_all_metrics_and_headline():
    out = explain_snapshot(_snap())
    assert out["account_id"] == "acct_123"
    assert "up $5,000.00" in out["headline"]
    keys = {m["key"] for m in out["metrics"]}
    assert keys == {"portfolio_value", "pnl", "volatility", "var", "sharpe"}
    # Every metric carries a non-empty plain-language explanation.
    assert all(m["plain"] for m in out["metrics"])
    # No previous snapshot -> no change narrative.
    assert out["changes"] == []


def test_explain_recovers_seed_cash_from_pv_minus_pnl():
    # seed = pv - pnl = 15000 - 5000 = 10000; pnl% = 50%.
    out = explain_snapshot(_snap(pv=15000.0, pnl=5000.0))
    pnl_metric = next(m for m in out["metrics"] if m["key"] == "pnl")
    assert "$10,000.00" in pnl_metric["plain"]
    assert "50.0%" in pnl_metric["plain"]


def test_explain_changes_explain_var_via_volatility():
    prev = _snap(pv=15000.0, pnl=5000.0, vol=0.002, var=49.5)
    curr = _snap(pv=15200.0, pnl=5200.0, vol=0.004, var=99.0)
    out = explain_snapshot(curr, prev)
    change_keys = {c["key"] for c in out["changes"]}
    assert "portfolio_value" in change_keys  # PV/PNL move reported
    assert "volatility" in change_keys       # vol up reported
    vol_change = next(c for c in out["changes"] if c["key"] == "volatility")
    assert "VaR" in vol_change["plain"]      # explains the VaR linkage


def test_explain_var_size_driver_when_vol_flat():
    prev = _snap(pv=10000.0, vol=0.004, var=66.0)
    curr = _snap(pv=15000.0, vol=0.004, var=99.0)  # vol unchanged, var up via size
    out = explain_snapshot(curr, prev)
    var_change = next(c for c in out["changes"] if c["key"] == "var")
    assert "portfolio value" in var_change["plain"].lower()


def test_explain_window_filling_note_when_zero():
    out = explain_snapshot(_snap(vol=0.0, var=0.0, sharpe=0.0))
    joined = " ".join(out["notes"]).lower()
    assert "not enough data yet" in joined or "accrued" in joined


def test_explain_endpoint_200(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    store = RiskStore(str(db))
    store.save_risk_snapshot(
        account_id="acct_123", portfolio_value=15000.0, pnl=5000.0,
        volatility=0.004, var=99.0, var_method="parametric", sharpe=0.3,
        computed_at="2026-01-01T00:00:00+00:00")
    store.close()

    resp = client.get("/risk/explain", params={"account_id": "acct_123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["account_id"] == "acct_123"
    assert body["headline"]
    assert len(body["metrics"]) == 5


def test_explain_endpoint_404_when_no_metrics(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    RiskStore(str(db)).close()  # empty store
    resp = client.get("/risk/explain", params={"account_id": "missing"})
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"
