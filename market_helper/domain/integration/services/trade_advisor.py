from __future__ import annotations

"""Trade advisor service: turn a portfolio snapshot + market regime into an
LLM advisory.

Speaks the OpenAI-compatible chat-completions wire format directly via stdlib
``urllib`` (no SDK dependency) against a local OpenClaw gateway. The single
network boundary is :func:`post_chat_completion`, which tests monkeypatch.

Read-only: this produces analysis text only and never places orders.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

DEFAULT_ENDPOINT_BASE_URL = "http://127.0.0.1:18789/v1"
DEFAULT_MODEL = "openclaw/trade-advisor"
_REQUEST_TIMEOUT_SECONDS = 120

# Regime snapshot fields we surface in the prompt, mapped to display labels.
_REGIME_FIELDS: tuple[tuple[str, str], ...] = (
    ("as of", "date"),
    ("regime", "final_regime"),
    ("confidence", "confidence"),
    ("growth score", "final_growth_score"),
    ("inflation score", "final_inflation_score"),
    ("risk score", "risk_score"),
    ("risk overlay on", "risk_overlay_on"),
    ("method disagreement", "disagreement_flag"),
)


@dataclass(frozen=True)
class AdvisorResult:
    advice: str
    model: str
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None


def _to_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def summarize_positions(positions: Sequence[Mapping[str, Any]], *, top_n: int = 15) -> str:
    """Compact, model-friendly summary of the portfolio's largest holdings."""
    total_mv = sum((_to_float(p.get("market_value")) or 0.0) for p in positions)
    ranked = sorted(
        positions,
        key=lambda p: abs(_to_float(p.get("market_value")) or 0.0),
        reverse=True,
    )
    lines = [
        f"Holdings: {len(positions)}; total market value: {total_mv:,.0f}",
        "Top holdings (symbol | weight | market_value | currency | unrealized_pnl):",
    ]
    for pos in ranked[:top_n]:
        weight = _to_float(pos.get("weight"))
        weight_text = f"{weight * 100:.1f}%" if weight is not None else str(pos.get("weight", ""))
        lines.append(
            f"- {pos.get('symbol', '?')} | {weight_text} | "
            f"{pos.get('market_value', '')} | {pos.get('currency', '')} | "
            f"{pos.get('unrealized_pnl', '')}"
        )
    return "\n".join(lines)


def summarize_regime(regime_snapshot: Optional[Mapping[str, Any]]) -> str:
    """Human/model-readable one-block summary of the latest regime snapshot."""
    if not regime_snapshot:
        return "Regime: (no regime snapshot available)"
    parts = [
        f"{label}={regime_snapshot[key]}"
        for label, key in _REGIME_FIELDS
        if regime_snapshot.get(key) is not None
    ]
    summary = "Regime: " + ", ".join(parts) if parts else "Regime: (snapshot present, no recognized fields)"
    disagreement = regime_snapshot.get("disagreement_summary")
    if disagreement:
        summary += f"\nDisagreement detail: {disagreement}"
    return summary


def build_advisor_prompt(
    positions: Sequence[Mapping[str, Any]],
    regime_snapshot: Optional[Mapping[str, Any]],
) -> str:
    """Build the single user turn describing the portfolio + regime and the ask."""
    return (
        "Base your analysis ONLY on the portfolio and market-regime data provided "
        "in this message. Ignore any previously remembered facts about my base "
        "currency, account, holdings, or target allocations; the data below is the "
        "single source of truth for this request.\n\n"
        "Here is my current portfolio and the prevailing market regime.\n\n"
        "## Portfolio\n"
        f"{summarize_positions(positions)}\n\n"
        "## Market regime\n"
        f"{summarize_regime(regime_snapshot)}\n\n"
        "## Please provide\n"
        "1. A one-paragraph thesis on how this portfolio is positioned for the current regime.\n"
        "2. The single biggest risk or concentration to watch.\n"
        "3. Notable allocation drift or imbalances.\n"
        "4. 3-5 concrete, actionable considerations (analysis only, not orders).\n"
    )


def post_chat_completion(
    *,
    endpoint_base_url: str,
    token: str,
    payload: Mapping[str, Any],
    session_key: Optional[str] = None,
    timeout: float = _REQUEST_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """POST an OpenAI-compatible chat-completions request. The network boundary."""
    url = endpoint_base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    if session_key:
        request.add_header("x-openclaw-session-key", session_key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:  # 4xx/5xx from the gateway
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"advisor endpoint returned HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:  # connection refused / DNS / timeout
        raise RuntimeError(f"could not reach advisor endpoint at {url}: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("advisor endpoint returned a non-JSON response") from exc


def request_advice(
    *,
    positions: Sequence[Mapping[str, Any]],
    regime_snapshot: Optional[Mapping[str, Any]],
    endpoint_base_url: str,
    token: str,
    model: str,
    session_key: Optional[str] = None,
) -> AdvisorResult:
    """Build the prompt, call the advisor endpoint, and parse the result."""
    prompt = build_advisor_prompt(positions, regime_snapshot)
    payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
    data = post_chat_completion(
        endpoint_base_url=endpoint_base_url,
        token=token,
        payload=payload,
        session_key=session_key,
    )
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("advisor endpoint returned no choices")
    advice = ((choices[0] or {}).get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return AdvisorResult(
        advice=advice.strip(),
        model=model,
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
    )


def render_advisory_markdown(
    *,
    positions: Sequence[Mapping[str, Any]],
    regime_snapshot: Optional[Mapping[str, Any]],
    result: AdvisorResult,
    as_of: Optional[str] = None,
) -> str:
    """Render the advisory artifact as markdown."""
    snapshot = regime_snapshot or {}
    header_as_of = as_of or (positions[0].get("as_of", "") if positions else "")
    lines = [
        "# Trade Advisory",
        "",
        f"- As of: {header_as_of}",
        f"- Regime: {snapshot.get('final_regime', '(unknown)')} "
        f"(confidence: {snapshot.get('confidence', '?')})",
        f"- Model: {result.model}",
    ]
    if result.prompt_tokens is not None:
        lines.append(
            f"- Tokens: prompt={result.prompt_tokens}, completion={result.completion_tokens}"
        )
    lines += [
        "",
        "## Advisory",
        "",
        result.advice,
        "",
        "---",
        "_Generated by market_helper trade_advisor. Informational analysis only, "
        "not investment advice._",
    ]
    return "\n".join(lines) + "\n"


__all__ = [
    "DEFAULT_ENDPOINT_BASE_URL",
    "DEFAULT_MODEL",
    "AdvisorResult",
    "summarize_positions",
    "summarize_regime",
    "build_advisor_prompt",
    "post_chat_completion",
    "request_advice",
    "render_advisory_markdown",
]
