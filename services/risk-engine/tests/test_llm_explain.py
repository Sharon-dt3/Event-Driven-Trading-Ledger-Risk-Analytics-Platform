"""Tests for the optional, grounded LLM explanation mode.

Offline and network-free: we never make a real API call. We verify:
- it's OFF by default (no RISK_LLM_ENABLED) -> generate returns None (fallback),
- enabled but no API key -> None (fallback),
- the grounded merge keeps deterministic values/keys/directions authoritative and
  only overlays LLM prose,
- the /risk/explain endpoint returns mode='rule' by default and degrades to
  rule-based text (mode='rule', llm_unavailable) when mode=llm but LLM is off,
- the capabilities endpoint reports the flag.
"""
import app.llm_explain as llm_explain
from app.explain import explain_snapshot
from app.llm_explain import _merge, generate_llm_narrative, is_enabled
from app.main import app
from app.store import RiskStore
from fastapi.testclient import TestClient

client = TestClient(app)


def _facts():
    return explain_snapshot({
        "account_id": "acct_123",
        "portfolio_value": 15000.0,
        "pnl": 5000.0,
        "volatility": 0.004,
        "var": 99.0,
        "var_method": "parametric",
        "sharpe": 0.3,
        "computed_at": "2026-01-01T00:00:00+00:00",
    })


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("RISK_LLM_ENABLED", raising=False)
    assert is_enabled() is False
    assert generate_llm_narrative(_facts()) is None


def test_enabled_without_api_key_falls_back(monkeypatch):
    monkeypatch.setenv("RISK_LLM_ENABLED", "true")
    monkeypatch.delenv("RISK_LLM_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert is_enabled() is True
    assert generate_llm_narrative(_facts()) is None


def test_network_error_falls_back(monkeypatch):
    monkeypatch.setenv("RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("RISK_LLM_API_KEY", "sk-test")

    def _boom(_cfg, _facts):
        raise OSError("no network in tests")

    monkeypatch.setattr(llm_explain, "_call_chat_completions", _boom)
    assert generate_llm_narrative(_facts()) is None


def test_merge_keeps_values_authoritative_and_overlays_prose():
    facts = _facts()
    llm = {
        "headline": "Great news — you're up nicely!",
        "summary": "Here's the friendly version.",
        "metrics": [
            {"key": "pnl", "label": "IGNORED LABEL", "plain": "You've gained money on paper."},
            {"key": "var", "plain": "On a rough day you might dip a little."},
        ],
        "changes": [],
        "notes": ["These update live."],
    }
    merged = _merge(facts, llm)

    assert merged["mode"] == "llm"
    assert merged["headline"] == "Great news — you're up nicely!"
    # Values and account fields remain from deterministic facts.
    assert merged["account_id"] == "acct_123"
    pnl = next(m for m in merged["metrics"] if m["key"] == "pnl")
    assert pnl["plain"] == "You've gained money on paper."
    assert pnl["label"] == "P&L"           # label stays authoritative (not overwritten)
    assert pnl["value"] == 5000.0          # value preserved
    # A metric the LLM didn't rewrite keeps its deterministic prose.
    pv = next(m for m in merged["metrics"] if m["key"] == "portfolio_value")
    assert "account is worth" in pv["plain"]


def test_successful_generation_merges(monkeypatch):
    monkeypatch.setenv("RISK_LLM_ENABLED", "true")
    monkeypatch.setenv("RISK_LLM_API_KEY", "sk-test")

    def _fake_call(_cfg, facts):
        return {
            "headline": "You're doing well!",
            "summary": "Friendly summary.",
            "metrics": [{"key": "pnl", "plain": "Up on paper."}],
            "changes": [],
            "notes": ["Live figures."],
        }

    monkeypatch.setattr(llm_explain, "_call_chat_completions", _fake_call)
    out = generate_llm_narrative(_facts())
    assert out is not None
    assert out["mode"] == "llm"
    assert out["headline"] == "You're doing well!"


def test_endpoint_default_mode_is_rule(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    monkeypatch.delenv("RISK_LLM_ENABLED", raising=False)
    store = RiskStore(str(db))
    store.save_risk_snapshot(
        account_id="acct_123", portfolio_value=15000.0, pnl=5000.0,
        volatility=0.004, var=99.0, var_method="parametric", sharpe=0.3,
        computed_at="2026-01-01T00:00:00+00:00")
    store.close()

    resp = client.get("/risk/explain", params={"account_id": "acct_123"})
    assert resp.status_code == 200
    assert resp.json()["mode"] == "rule"


def test_endpoint_llm_mode_degrades_when_disabled(tmp_path, monkeypatch):
    db = tmp_path / "risk.db"
    monkeypatch.setenv("RISK_DB_PATH", str(db))
    monkeypatch.delenv("RISK_LLM_ENABLED", raising=False)
    store = RiskStore(str(db))
    store.save_risk_snapshot(
        account_id="acct_123", portfolio_value=15000.0, pnl=5000.0,
        volatility=0.004, var=99.0, var_method="parametric", sharpe=0.3,
        computed_at="2026-01-01T00:00:00+00:00")
    store.close()

    resp = client.get("/risk/explain", params={"account_id": "acct_123", "mode": "llm"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "rule"            # transparent fallback
    assert body.get("llm_unavailable") is True


def test_capabilities_endpoint(monkeypatch):
    monkeypatch.delenv("RISK_LLM_ENABLED", raising=False)
    resp = client.get("/risk/explain/capabilities")
    assert resp.status_code == 200
    assert resp.json() == {"llm_enabled": False}
