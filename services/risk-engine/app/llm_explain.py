"""Optional LLM-backed risk explanation (grounded, dependency-free, opt-in).

This is an *optional* enhancement layered on top of the deterministic
``explain_snapshot()`` facts. When enabled it asks an OpenAI-compatible Chat
Completions endpoint to rewrite those facts into a friendlier, conversational
narrative for users without financial expertise. Crucially it is **grounded**:
the model is given the already-computed numbers and plain-language facts and is
instructed to use ONLY those — it must not invent figures or financial advice.

Safety / design guarantees:
- **Off by default.** Controlled by ``RISK_LLM_ENABLED`` (falsy unless set true).
- **No new dependencies.** Uses only the Python standard library (``urllib``),
  so the service image and requirements are unchanged.
- **Never breaks the endpoint.** Any problem (disabled, missing API key, network
  error, bad response, timeout) makes ``generate_llm_narrative`` return ``None``;
  the caller then serves the deterministic rule-based explanation. The LLM is
  strictly additive and can only *replace prose*, never the numbers.
- **Grounded output shape.** The model is asked to return the same JSON shape as
  the rule-based narrative (headline, summary, metrics[].plain, changes[].plain,
  notes[]); we merge only its prose back onto the deterministic structure so the
  metric keys/labels/values and change directions always stay authoritative.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

logger = logging.getLogger("risk-engine.llm")


def _env(name: str, default: str = "") -> str:
    v = os.getenv(name)
    return v if v is not None else default


def is_enabled() -> bool:
    """True only when explicitly turned on via ``RISK_LLM_ENABLED``."""
    return _env("RISK_LLM_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on")


def _config() -> Dict[str, Any]:
    return {
        "enabled": is_enabled(),
        "api_key": _env("RISK_LLM_API_KEY") or _env("OPENAI_API_KEY"),
        "base_url": _env("RISK_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        "model": _env("RISK_LLM_MODEL", "gpt-4o-mini"),
        "timeout": float(_env("RISK_LLM_TIMEOUT_MS", "8000") or "8000") / 1000.0,
    }


_SYSTEM_PROMPT = (
    "You are a friendly financial coach helping a retail user who has NO finance "
    "expertise understand their portfolio risk. You will be given a JSON object of "
    "ALREADY-COMPUTED facts (headline, per-metric plain explanations, what changed, "
    "and caveats). Rewrite these into a warm, clear, encouraging narrative.\n\n"
    "STRICT RULES:\n"
    "1. Use ONLY the numbers and facts provided. NEVER invent or alter any figure.\n"
    "2. Do NOT give buy/sell recommendations or financial advice.\n"
    "3. Keep it concise and jargon-free; briefly define any term you must use.\n"
    "4. Preserve the factual relationships stated (e.g. VaR is proportional to "
    "volatility and portfolio size).\n"
    "5. Return ONLY a JSON object with this exact shape (no markdown, no extra keys):\n"
    '{"headline": str, "summary": str, '
    '"metrics": [{"key": str, "label": str, "plain": str}], '
    '"changes": [{"key": str, "direction": str, "plain": str}], '
    '"notes": [str]}\n'
    "The metrics and changes arrays MUST keep the same keys/labels/directions as the "
    "input; only rewrite the 'plain' prose and the headline/summary/notes."
)


def _build_user_payload(facts: Dict[str, Any]) -> str:
    slim = {
        "headline": facts.get("headline"),
        "summary": facts.get("summary"),
        "metrics": [
            {"key": m.get("key"), "label": m.get("label"), "plain": m.get("plain")}
            for m in facts.get("metrics", [])
        ],
        "changes": [
            {"key": c.get("key"), "direction": c.get("direction"), "plain": c.get("plain")}
            for c in facts.get("changes", [])
        ],
        "notes": list(facts.get("notes", [])),
    }
    return json.dumps(slim, ensure_ascii=False)


def _call_chat_completions(cfg: Dict[str, Any], facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    url = f"{cfg['base_url']}/chat/completions"
    body = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_payload(facts)},
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {cfg['api_key']}")

    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
        raw = resp.read().decode("utf-8")
    parsed = json.loads(raw)
    content = parsed["choices"][0]["message"]["content"]
    return json.loads(content)


def _merge(facts: Dict[str, Any], llm: Dict[str, Any]) -> Dict[str, Any]:
    """Overlay LLM prose onto the deterministic structure.

    Only prose fields (headline, summary, notes, and each metric/change ``plain``)
    are taken from the model; keys, labels, values and directions remain from the
    authoritative deterministic facts so nothing factual can drift.
    """
    out = dict(facts)  # keep account_id, computed_at, values, directions, etc.

    if isinstance(llm.get("headline"), str) and llm["headline"].strip():
        out["headline"] = llm["headline"].strip()
    if isinstance(llm.get("summary"), str) and llm["summary"].strip():
        out["summary"] = llm["summary"].strip()
    if isinstance(llm.get("notes"), list) and llm["notes"]:
        out["notes"] = [str(n) for n in llm["notes"] if str(n).strip()]

    # Map LLM prose by metric/change key, but keep our structure/order.
    llm_metric_plain = {
        m.get("key"): m.get("plain")
        for m in llm.get("metrics", [])
        if isinstance(m, dict) and isinstance(m.get("plain"), str) and m.get("plain").strip()
    }
    out_metrics: List[Dict[str, Any]] = []
    for m in facts.get("metrics", []):
        mm = dict(m)
        if m.get("key") in llm_metric_plain:
            mm["plain"] = llm_metric_plain[m["key"]].strip()
        out_metrics.append(mm)
    out["metrics"] = out_metrics

    llm_change_plain = {
        c.get("key"): c.get("plain")
        for c in llm.get("changes", [])
        if isinstance(c, dict) and isinstance(c.get("plain"), str) and c.get("plain").strip()
    }
    out_changes: List[Dict[str, Any]] = []
    for c in facts.get("changes", []):
        cc = dict(c)
        if c.get("key") in llm_change_plain:
            cc["plain"] = llm_change_plain[c["key"]].strip()
        out_changes.append(cc)
    out["changes"] = out_changes

    out["mode"] = "llm"
    return out


def generate_llm_narrative(facts: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return an LLM-rewritten, grounded narrative, or ``None`` to fall back.

    ``facts`` is the deterministic ``explain_snapshot()`` output. Returns ``None``
    (so the caller uses the rule-based text) when the LLM mode is disabled, no API
    key is configured, or any error occurs during the call.
    """
    cfg = _config()
    if not cfg["enabled"]:
        return None
    if not cfg["api_key"]:
        logger.info("llm_explain_skipped", extra={"extra_fields": {"reason": "no_api_key"}})
        return None

    try:
        llm = _call_chat_completions(cfg, facts)
    except (urllib.error.URLError, TimeoutError, OSError) as ex:
        logger.warning("llm_explain_network_error", extra={"extra_fields": {"error": str(ex)}})
        return None
    except (KeyError, ValueError, TypeError) as ex:
        logger.warning("llm_explain_bad_response", extra={"extra_fields": {"error": str(ex)}})
        return None

    if not isinstance(llm, dict):
        return None
    try:
        return _merge(facts, llm)
    except (KeyError, ValueError, TypeError) as ex:
        logger.warning("llm_explain_merge_error", extra={"extra_fields": {"error": str(ex)}})
        return None
