"""Crystallize the premium-screen preset — the §2 closed loop, made real.

The AI Plus pane is where a better screen is *discovered* ("IV/RV ≥ 1.15 filters
the junk"); this module is how it **crystallizes into the Rule-based preset** —
config, not code. The editor writes ONLY the four ``premium_screen`` knob values
in ``configs/option_advisor/advisor_rules.yaml`` via targeted line edits, so the
file's research comments survive byte-for-byte. Values are clamped to bounded,
validated bands (the rule-based pane never accepts free-form input).

The Option scan passes this YAML as ``rules_path``, so a saved preset takes
effect on the next scan.
"""

from __future__ import annotations

import re
from pathlib import Path

from market_helper.app.paths import CONFIGS_DIR

DEFAULT_RULES_YAML = CONFIGS_DIR / "option_advisor" / "advisor_rules.yaml"

# Bounded bands per knob: (lo, hi, is_int). Out-of-band input is CLAMPED, never
# rejected with a crash and never written raw — the preset stays sane by
# construction (same philosophy as the bounded UI controls).
PREMIUM_SCREEN_BOUNDS: dict[str, tuple[float, float, bool]] = {
    "target_yield_annualized": (0.05, 2.0, False),  # 5%–200%/yr normalization anchor
    "vrp_ratio_span": (0.05, 2.0, False),           # IV/RV−1 span that scores richness 1.0
    "min_vrp_ratio": (0.5, 2.0, False),             # below 1.0 = selling cheap vol
    "manage_dte": (7.0, 45.0, True),                # the researched ~21 DTE management point
}


def advisor_rules_path() -> Path:
    """The canonical rules YAML (what the Option scan should pass as ``rules_path``)."""
    return DEFAULT_RULES_YAML


def load_premium_screen(path: str | Path | None = None) -> dict:
    """Current effective premium-screen knobs (YAML merged over defaults)."""
    from market_helper.domain.option_advisor.config import load_rules

    p = Path(path) if path else DEFAULT_RULES_YAML
    rules = load_rules(p if p.exists() else None)
    return dict(rules.get("premium_screen", {}))


def clamp_premium_screen(knobs: dict) -> dict:
    """Validate + clamp the four knobs into their bounded bands (pure)."""
    out: dict = {}
    for key, (lo, hi, is_int) in PREMIUM_SCREEN_BOUNDS.items():
        if key not in knobs or knobs[key] is None:
            continue
        try:
            val = float(knobs[key])
        except (TypeError, ValueError):
            continue
        val = min(max(val, lo), hi)
        out[key] = int(round(val)) if is_int else round(val, 4)
    return out


def _fmt(key: str, value) -> str:
    return str(value) if PREMIUM_SCREEN_BOUNDS[key][2] else f"{value:g}"


def save_premium_screen(knobs: dict, path: str | Path | None = None) -> dict:
    """Write the clamped knobs into the YAML via **targeted line edits**.

    Only the value on each ``<key>:`` line changes — comments (the research
    rationale lives in them) and every other byte survive. Keys absent from the
    file are appended under a (possibly new) ``premium_screen:`` block. Returns
    the clamped knobs that were written.
    """
    clean = clamp_premium_screen(knobs)
    if not clean:
        return {}
    p = Path(path) if path else DEFAULT_RULES_YAML
    text = p.read_text(encoding="utf-8") if p.exists() else ""

    missing: list[str] = []
    for key, value in clean.items():
        pattern = re.compile(rf"^(\s*{re.escape(key)}\s*:\s*)[^#\n]*?(\s*(?:#.*)?)$", re.MULTILINE)
        new_text, n = pattern.subn(lambda m, v=_fmt(key, value): f"{m.group(1)}{v}{m.group(2)}", text, count=1)
        if n:
            text = new_text
        else:
            missing.append(key)

    if missing:
        if not re.search(r"^premium_screen\s*:", text, re.MULTILINE):
            text = text.rstrip("\n") + "\n\npremium_screen:\n"
        block_lines = "".join(f"  {k}: {_fmt(k, clean[k])}\n" for k in missing)
        text = re.sub(r"^(premium_screen\s*:\s*\n)", lambda m: m.group(1) + block_lines, text,
                      count=1, flags=re.MULTILINE)

    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return clean
