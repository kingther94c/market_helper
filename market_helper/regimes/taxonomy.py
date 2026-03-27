from __future__ import annotations

REGIME_DEFLATIONARY_CRISIS = "Deflationary Crisis"
REGIME_INFLATIONARY_CRISIS = "Inflationary Crisis"
REGIME_RECOVERY_PIVOT = "Recovery / Pivot"
REGIME_GOLDILOCKS = "Goldilocks Expansion"
REGIME_REFLATION_TIGHTENING = "Reflation / Tightening-with-growth"
REGIME_DEFLATIONARY_SLOWDOWN = "Deflationary Slowdown"
REGIME_STAGFLATION = "Stagflation / Supply Shock"

REGIME_LABELS = [
    REGIME_DEFLATIONARY_CRISIS,
    REGIME_INFLATIONARY_CRISIS,
    REGIME_RECOVERY_PIVOT,
    REGIME_GOLDILOCKS,
    REGIME_REFLATION_TIGHTENING,
    REGIME_DEFLATIONARY_SLOWDOWN,
    REGIME_STAGFLATION,
]

REGIME_INTERPRETATIONS = {
    REGIME_DEFLATIONARY_CRISIS: "Acute stress with falling growth and a disinflationary rates impulse.",
    REGIME_INFLATIONARY_CRISIS: "Acute stress with rising rates/inflation shock pressure.",
    REGIME_RECOVERY_PIVOT: "Post-crisis transition where stress fades and risk appetite starts to improve.",
    REGIME_GOLDILOCKS: "Low stress with supportive growth and stable rates backdrop.",
    REGIME_REFLATION_TIGHTENING: "Growth remains resilient while rates pressure is elevated.",
    REGIME_DEFLATIONARY_SLOWDOWN: "Growth deceleration with limited inflation pressure.",
    REGIME_STAGFLATION: "Weak growth with elevated rates/inflation stress.",
}
