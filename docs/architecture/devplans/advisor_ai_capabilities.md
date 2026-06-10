# Advisor AI — capability framework (tools · skills · knowledge)

The advisor AI (the OpenClaw-gateway synthesis layer, used today by the Tactical
Trade Ideas module) has a **systematic, extensible** capability set with one home
each for the three things it can use:

| Capability | What it is | Home |
|---|---|---|
| **Tools** | read-only local functions the AI may *call* mid-answer to pull live data | `trade_advisor/ai/tools.py` (framework) + per-domain `ai_tools.py` |
| **Skills** | the *injected prompts per task* (the harness-selected production prompt + alternatives) | `trade_advisor/ai/skills.py` (`PromptSkill`) + per-domain `ai_tools.py` |
| **Knowledge** | reference facts the AI is grounded on (invariants, honesty ladder, regime quadrants, module map) | `trade_advisor/ai/skills.py` (`KnowledgeEntry`) + per-domain |

Everything is assembled + listed in one place:
`trade_advisor/ai/capabilities.py` → `build_advisor_ai_capabilities()` →
`.describe()` / `.as_dict()`.

**Hard invariant:** every tool is `read_only=True` (the registry refuses anything
else) and the AI is forbidden from emitting orders/sizes — the whole advisor is
read-only w.r.t. the broker (ADR 0001).

---

## How tool-calling actually works (important)

The OpenClaw gateway **ignores client-supplied OpenAI `tools`** (probe, 2026-06-07:
it has its own internal tool registry and does not honor ours, so native
`tool_calls` never come back). So `run_tool_chat` drives a **gateway-agnostic
structured-text protocol** instead:

1. We append a protocol block to the system turn listing the tools and the format.
2. To call a tool the model replies with only a fenced block:
   ````
   ```tool_call
   {"name": "get_price_trend", "arguments": {"symbol": "SPY"}}
   ```
   ````
3. `run_tool_chat` parses it, dispatches the read-only function, and feeds the
   result back as a ```tool_result``` user turn; it loops to a `max_rounds` cap,
   then returns the final answer (tool blocks stripped) + a transparent trace of
   every call.

This works with any plain chat-completions endpoint. `AiToolRegistry.to_openai_tools()`
is kept for the day a gateway supports native function-calling — only the loop in
`run_tool_chat` would switch.

Verified live: the AI called `get_regime_snapshot` and `get_price_trend("SPY")`,
received real data (Reflation; SPY vol term-structure + "up" trend), and cited it
— 0 order leakage.

---

## Current manifest

```
## Tools (9) — read-only functions the AI can call
# research tools (domain/tactical_ideas/ai_tools.py)
- get_regime_snapshot(): latest macro regime quadrant + growth/inflation/risk scores + crisis flag
- get_policy_expert(): forward policy-expert tilt (leading expert, sleeve weights) + trending momentum
- get_tactical_anchors(): the rule-based tactical idea anchors that fired (theme/thesis/evidence/invalidation)
- get_price_trend(symbol): realized vol (1m/3m/6m/1y) + SMA trend for one ticker
- get_tactical_edge(): the external daily Tactical Edge brief cards (title/status/mechanism/skeptic/scores)
# cross-module tools (trade_advisor/ai/advisor_tools.py, v2.1) — the AI sees what the modules see
- get_portfolio_book(): live book — funded AUM, stock holdings, held options + futures (signed notionals)
- get_fx_decision(): FX target-vs-current join — per-ccy gap (ct + USD) + the "at target" mix (cached artifact)
- get_roll_yields(): held-roots two-contract roll yields from the CACHED quote artifact (never fetches itself)
- get_option_scan(): the latest persisted rule-based option scan (inputs + per-idea screen/label/yield/IV/RV)

## Skills (3) — injected prompts for the `tactical_brief` task
- tactical_default     : conviction table + "Anchors I'd fade" + monitorable invalidation (harness-selected production prompt)
- tactical_adversarial : every leading idea stress-tested with an explicit bear case
- tactical_terse       : compact conviction table + a single top pick (quick scan)

## Knowledge (7) — facts the AI is grounded on
- read_only_invariant, data_mode_ladder, triage_labels, regime_quadrants, cockpit_modules   (core)
- tactical_themes, derived_quadrant                                                          (tactical)
```

Every AI Plus pane gets the full 9-tool registry (`build_advisor_tool_registry()`),
so e.g. the Option pane can critique the persisted scan and the FX pane can re-pull
the live gap mid-refinement. None of the cross-module tools triggers a network
fetch — they serve cached/local state only (quotes are fetched solely via the
dashboard's explicit Fetch button). Regenerate with
`build_advisor_ai_capabilities().describe()`.

---

## Extending it (the openness seam)

A domain contributes capabilities from its own `ai_tools.py`; nothing else changes.

**Add a tool** — register a read-only function:
```python
reg = AiToolRegistry()

@reg.tool("get_fx_carry", "Current FX carry tilt: before/after exposure + carry impact.",
          {"type": "object", "properties": {}, "additionalProperties": False})
def get_fx_carry() -> dict:
    ...  # READ-ONLY: fetch/compute and return JSON-able data. Never place/size/mutate.
```
Then add it to the domain's tool registry and wire that registry into
`build_advisor_ai_capabilities()` (and into `run_tool_chat` for the relevant task).

**Add a skill** (an injected prompt for a task):
```python
PromptSkill(name="fx_carry_default", task="fx_carry_brief",
            when_to_use="Explain the FX carry tilt + its basis-risk cost.",
            system="...read-only framing + order guard...", ask="...response shape...")
```
Register it in the domain's `*_skills()`; pick per task via `SkillRegistry.for_task(task)`.

**Add knowledge** (a grounding fact):
```python
KnowledgeEntry("fx_carry_method", "FX", "Carry is rate-approximated (no forward curve in-repo)...", ("fx", "honesty"))
```
Register it in the domain's `*_knowledge()`; inject a selection with
`knowledge_system_block(book, names=[...])` or serve it via a `get_knowledge` tool.

**Checklist for any new tool:** read-only; JSON-serializable return; a clear
description + JSON-schema params (so the model knows when/how to call it); errors
are returned (the registry wraps them), never raised to the user.

---

## Files

- `market_helper/trade_advisor/ai/tools.py` — `AiTool`, `AiToolRegistry`, `run_tool_chat`, protocol.
- `market_helper/trade_advisor/ai/skills.py` — `PromptSkill`, `KnowledgeEntry`, registries, core knowledge.
- `market_helper/trade_advisor/ai/capabilities.py` — `build_advisor_ai_capabilities()` (the manifest).
- `market_helper/domain/tactical_ideas/ai_tools.py` — the tactical tools/skills/knowledge + tool-enabled messages.
- Tests: `tests/unit/trade_advisor/ai/test_{tools,skills,capabilities}.py`, `tests/unit/domain/tactical_ideas/test_ai_tools.py`.
