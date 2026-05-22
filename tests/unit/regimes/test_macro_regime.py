from __future__ import annotations

import pandas as pd
import pytest

from market_helper.data_sources.fred.macro_panel import ConceptSpec, SeriesSpec
from market_helper.regimes.axes import QUADRANT_GOLDILOCKS
from market_helper.regimes.methods.macro_regime import (
    MacroRegimeConfig,
    MacroRegimeMethod,
    compute_macro_axis_scores,
)


def _concept(name: str, axis: str, members: dict[str, float], weight: float = 1.0) -> ConceptSpec:
    return ConceptSpec(name=name, axis=axis, weight=weight, members=members)


def test_concept_aggregation_weights_within_then_across() -> None:
    """Two concepts on growth: A weight 1, B weight 0.5; A has two members
    (50/50 within), B has one member. Across-concept weighted mean should be
    ((A_score * 1) + (B_score * 0.5)) / 1.5."""
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=3),
            "X": [1.0, 1.0, 1.0],
            "Y": [-1.0, -1.0, -1.0],
            "Z": [2.0, 2.0, 2.0],
        }
    )
    specs = [
        SeriesSpec(series_id="X", axis="growth", transform="level"),
        SeriesSpec(series_id="Y", axis="growth", transform="level"),
        SeriesSpec(series_id="Z", axis="growth", transform="level"),
    ]
    concepts = [
        _concept("A", "growth", {"X": 0.5, "Y": 0.5}, weight=1.0),
        _concept("B", "growth", {"Z": 1.0}, weight=0.5),
    ]
    scores = compute_macro_axis_scores(panel, specs, concepts)
    # A_score = (1*0.5 + (-1)*0.5)/1 = 0; B_score = 2.
    # axis = (0*1 + 2*0.5) / 1.5 = 0.6667
    assert scores["growth"].iloc[-1] == pytest.approx(2 / 3)


def test_concept_uses_only_available_members() -> None:
    """Missing series falls out of the within-weight denominator."""
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=3),
            "X": [1.0, 1.0, 1.0],
            # Y intentionally absent from panel.
        }
    )
    specs = [
        SeriesSpec(series_id="X", axis="growth", transform="level"),
        SeriesSpec(series_id="Y", axis="growth", transform="level"),
    ]
    concepts = [
        _concept("A", "growth", {"X": 0.5, "Y": 0.5}, weight=1.0),
    ]
    scores = compute_macro_axis_scores(panel, specs, concepts)
    assert scores["growth"].iloc[-1] == pytest.approx(1.0)


def test_concept_emits_concept_score_columns() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=3),
            "X": [1.0, 1.0, 1.0],
        }
    )
    specs = [SeriesSpec(series_id="X", axis="growth", transform="level")]
    concepts = [_concept("alpha", "growth", {"X": 1.0}, weight=1.0)]
    scores = compute_macro_axis_scores(panel, specs, concepts)
    assert "concept:growth:alpha" in scores.columns
    assert "contrib:X" in scores.columns


def test_macro_method_classify_growth_positive_inflation_negative_is_goldilocks() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=5),
            "G": [1.0] * 5,
            "I": [-1.0] * 5,
        }
    )
    specs = [
        SeriesSpec(series_id="G", axis="growth", transform="level"),
        SeriesSpec(series_id="I", axis="inflation", transform="level"),
    ]
    concepts = [
        _concept("g", "growth", {"G": 1.0}, weight=1.0),
        _concept("i", "inflation", {"I": 1.0}, weight=1.0),
    ]
    method = MacroRegimeMethod(specs, concepts, config=MacroRegimeConfig(min_consecutive_days=1))
    results = method.classify(panel)
    assert results[-1].quadrant.quadrant == QUADRANT_GOLDILOCKS


def test_macro_minmax_normalization_scales_into_configured_bounds() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=10),
            "G": [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0],
        }
    )
    specs = [
        SeriesSpec(
            series_id="G",
            axis="growth",
            transform="level",
            normalization="minmax",
            minmax_lower=-1.0,
            minmax_upper=1.0,
            minmax_window_bdays=5,
        )
    ]
    concepts = [_concept("g", "growth", {"G": 1.0}, weight=1.0)]
    scores = compute_macro_axis_scores(panel, specs, concepts)
    growth = scores["growth"].dropna()
    assert ((growth >= -1.0 - 1e-9) & (growth <= 1.0 + 1e-9)).all()
    assert growth.iloc[-1] == pytest.approx(1.0)


def test_macro_percentile_normalization_returns_values_in_minus_one_to_one() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=12),
            "G": list(range(12)),
        }
    )
    specs = [
        SeriesSpec(
            series_id="G",
            axis="growth",
            transform="level",
            normalization="percentile",
            percentile_window_bdays=10,
        )
    ]
    concepts = [_concept("g", "growth", {"G": 1.0}, weight=1.0)]
    scores = compute_macro_axis_scores(panel, specs, concepts)
    growth = scores["growth"].dropna()
    assert ((growth >= -1.0 - 1e-9) & (growth <= 1.0 + 1e-9)).all()
    assert growth.iloc[-1] == pytest.approx(1.0)


def test_macro_tanh_compression_bounds_contributions() -> None:
    """tanh(z/2) should bound a 6σ z-score below 1 even before within-weights."""
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=300),
            "G": [float(i) for i in range(300)],
        }
    )
    specs = [
        SeriesSpec(
            series_id="G",
            axis="growth",
            transform="level",
            normalization="zscore",
            zscore_window_bdays=30,
            zscore_min_periods=30,
            zscore_clip=10.0,  # don't pre-clip; let tanh do the bounding
        )
    ]
    concepts = [_concept("g", "growth", {"G": 1.0}, weight=1.0)]
    cfg = MacroRegimeConfig(compression="tanh", compression_k=2.0)
    scores = compute_macro_axis_scores(panel, specs, concepts, config=cfg)
    contrib = scores["contrib:G"].dropna()
    assert ((contrib > -1.0) & (contrib < 1.0)).all()


def test_recency_weighting_decays_within_concept_member_weights() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=1),
            "STALE": [1.0],
            "_age_bdays:STALE": [10.0],
            "FRESH": [-1.0],
            "_age_bdays:FRESH": [0.0],
        }
    )
    specs = [
        SeriesSpec(series_id="STALE", axis="growth", transform="level"),
        SeriesSpec(series_id="FRESH", axis="growth", transform="level"),
    ]
    concepts = [_concept("g", "growth", {"STALE": 1.0, "FRESH": 1.0}, weight=1.0)]
    cfg = MacroRegimeConfig(
        recency_weighting_enabled=True,
        recency_half_life_bdays=10.0,
        recency_min_weight=0.0,
    )

    scores = compute_macro_axis_scores(panel, specs, concepts, config=cfg).iloc[-1]

    assert scores["recency_weight:STALE"] == pytest.approx(0.5)
    assert scores["recency_weight:FRESH"] == pytest.approx(1.0)
    assert scores["growth"] == pytest.approx(-1 / 3)
    assert scores["growth_confidence"] == pytest.approx(0.75)


def test_recency_weighting_scales_concept_weight_without_overwriting_basket_weight() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=1),
            "A": [1.0],
            "_age_bdays:A": [10.0],
            "B": [-1.0],
            "_age_bdays:B": [0.0],
        }
    )
    specs = [
        SeriesSpec(series_id="A", axis="growth", transform="level"),
        SeriesSpec(series_id="B", axis="growth", transform="level"),
    ]
    concepts = [
        _concept("stale_concept", "growth", {"A": 1.0}, weight=2.0),
        _concept("fresh_concept", "growth", {"B": 1.0}, weight=1.0),
    ]
    cfg = MacroRegimeConfig(
        recency_weighting_enabled=True,
        recency_half_life_bdays=10.0,
        recency_min_weight=0.0,
    )

    scores = compute_macro_axis_scores(panel, specs, concepts, config=cfg).iloc[-1]

    # Semantic concept weights remain 2:1, but stale_concept uses only 50% of
    # its max weight, so effective concept weights are tied at 1:1.
    assert scores["growth"] == pytest.approx(0.0)
    assert scores["growth_confidence"] == pytest.approx(2 / 3)


def test_macro_engine_block_round_trip_through_yaml(tmp_path) -> None:
    from market_helper.regimes.methods.macro_regime import load_macro_regime_config

    config_path = tmp_path / "fred_series.yml"
    config_path.write_text(
        "engine:\n"
        "  zscore_window_bdays: 100\n"
        "  zscore_clip: 2.5\n"
        "  compression: tanh\n"
        "  compression_k: 1.5\n"
        "  recency_weighting:\n"
        "    enabled: true\n"
        "    half_life_bdays: 13\n"
        "    min_weight: 0.2\n"
        "  min_consecutive_days: 7\n"
        "series: []\n"
    )
    cfg = load_macro_regime_config(config_path)
    assert cfg.zscore_window_bdays == 100
    assert cfg.zscore_clip == 2.5
    assert cfg.compression == "tanh"
    assert cfg.compression_k == 1.5
    assert cfg.recency_weighting_enabled is True
    assert cfg.recency_half_life_bdays == 13
    assert cfg.recency_min_weight == 0.2
    assert cfg.min_consecutive_days == 7


def test_macro_per_series_zscore_window_overrides_engine_default() -> None:
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=200),
            "G": [float(i) for i in range(200)],
        }
    )
    spec_default = SeriesSpec(
        series_id="G",
        axis="growth",
        transform="level",
        normalization="zscore",
    )
    spec_override = SeriesSpec(
        series_id="G",
        axis="growth",
        transform="level",
        normalization="zscore",
        zscore_window_bdays=20,
        zscore_min_periods=20,
    )
    concepts = [_concept("g", "growth", {"G": 1.0}, weight=1.0)]
    config = MacroRegimeConfig(zscore_window_bdays=2520, min_periods=252)
    default_score = compute_macro_axis_scores(panel, [spec_default], concepts, config=config).iloc[-1]
    override_score = compute_macro_axis_scores(panel, [spec_override], concepts, config=config).iloc[-1]
    import math as _math
    assert _math.isnan(default_score["growth"])
    assert not _math.isnan(override_score["growth"])


def test_concept_loader_round_trips_growth_and_inflation_blocks(tmp_path) -> None:
    from market_helper.data_sources.fred.macro_panel import load_concept_specs

    p = tmp_path / "fred_series.yml"
    p.write_text(
        "series: []\n"
        "growth_concepts:\n"
        "  labor:\n"
        "    weight: 1.0\n"
        "    series:\n"
        "      UNRATE: 0.5\n"
        "      PAYEMS: 0.5\n"
        "inflation_concepts:\n"
        "  expectations:\n"
        "    weight: 1.25\n"
        "    series:\n"
        "      T5YIFR: 1.0\n"
    )
    concepts = load_concept_specs(p)
    by_name = {(c.axis, c.name): c for c in concepts}
    labor = by_name[("growth", "labor")]
    assert labor.weight == 1.0
    assert labor.members == {"UNRATE": 0.5, "PAYEMS": 0.5}
    expectations = by_name[("inflation", "expectations")]
    assert expectations.weight == 1.25
    assert expectations.members == {"T5YIFR": 1.0}


def test_resolve_decay_half_life_prefers_explicit_then_hint_then_default() -> None:
    from market_helper.data_sources.fred.macro_panel import resolve_decay_half_life_bdays

    # Explicit override wins regardless of hint
    explicit = SeriesSpec(
        series_id="X", axis="growth", transform="level",
        frequency_hint="monthly", decay_half_life_bdays=3.0,
    )
    assert resolve_decay_half_life_bdays(explicit, default=21.0) == 3.0

    # No explicit → fall through to hint
    weekly = SeriesSpec(series_id="W", axis="growth", transform="level", frequency_hint="weekly")
    monthly = SeriesSpec(series_id="M", axis="growth", transform="level", frequency_hint="monthly")
    quarterly = SeriesSpec(series_id="Q", axis="growth", transform="level", frequency_hint="quarterly")
    assert resolve_decay_half_life_bdays(weekly, default=21.0) == 5.0
    assert resolve_decay_half_life_bdays(monthly, default=21.0) == 22.0
    assert resolve_decay_half_life_bdays(quarterly, default=21.0) == 66.0

    # No explicit and no hint → config default
    bare = SeriesSpec(series_id="B", axis="growth", transform="level")
    assert resolve_decay_half_life_bdays(bare, default=21.0) == 21.0


def test_per_series_decay_weekly_decays_faster_than_monthly_at_same_age() -> None:
    # Two series, same age (22 bdays — one monthly cadence). The weekly
    # series should already be well below 0.5 weight; the monthly series
    # should be roughly at 0.5 weight (one half-life elapsed).
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=1),
            "WEEKLY": [1.0],
            "_age_bdays:WEEKLY": [22.0],
            "MONTHLY": [1.0],
            "_age_bdays:MONTHLY": [22.0],
        }
    )
    specs = [
        SeriesSpec(series_id="WEEKLY", axis="growth", transform="level", frequency_hint="weekly"),
        SeriesSpec(series_id="MONTHLY", axis="growth", transform="level", frequency_hint="monthly"),
    ]
    concepts = [_concept("g", "growth", {"WEEKLY": 1.0, "MONTHLY": 1.0}, weight=1.0)]
    cfg = MacroRegimeConfig(
        recency_weighting_enabled=True,
        recency_half_life_bdays=21.0,  # global default — ignored when hint resolves
        recency_min_weight=0.0,
    )

    scores = compute_macro_axis_scores(panel, specs, concepts, config=cfg).iloc[-1]
    # Weekly: half_life=5, age=22 → 0.5^(22/5) ≈ 0.0476
    assert scores["recency_weight:WEEKLY"] == pytest.approx(0.5 ** (22.0 / 5.0), rel=1e-6)
    # Monthly: half_life=22, age=22 → 0.5
    assert scores["recency_weight:MONTHLY"] == pytest.approx(0.5, rel=1e-6)
    # Weekly should be MUCH more decayed than monthly
    assert scores["recency_weight:WEEKLY"] < scores["recency_weight:MONTHLY"] / 5


def test_explicit_decay_half_life_overrides_frequency_hint() -> None:
    # Even with frequency_hint="weekly" (default 5 bday half-life), an
    # explicit decay_half_life_bdays=22 on the spec should give the same
    # weight as a monthly series at age 22.
    panel = pd.DataFrame(
        {
            "date": pd.bdate_range("2024-01-01", periods=1),
            "WEEKLY_OVERRIDE": [1.0],
            "_age_bdays:WEEKLY_OVERRIDE": [22.0],
        }
    )
    specs = [
        SeriesSpec(
            series_id="WEEKLY_OVERRIDE",
            axis="growth",
            transform="level",
            frequency_hint="weekly",
            decay_half_life_bdays=22.0,
        ),
    ]
    concepts = [_concept("g", "growth", {"WEEKLY_OVERRIDE": 1.0}, weight=1.0)]
    cfg = MacroRegimeConfig(
        recency_weighting_enabled=True,
        recency_half_life_bdays=999.0,
        recency_min_weight=0.0,
    )
    scores = compute_macro_axis_scores(panel, specs, concepts, config=cfg).iloc[-1]
    assert scores["recency_weight:WEEKLY_OVERRIDE"] == pytest.approx(0.5)


def test_yaml_loader_picks_up_decay_half_life_per_series(tmp_path) -> None:
    from market_helper.data_sources.fred.macro_panel import load_series_specs

    p = tmp_path / "fred_series.yml"
    p.write_text(
        "series:\n"
        "  - series_id: CLAIMS\n"
        "    axis: growth\n"
        "    transform: level\n"
        "    frequency_hint: weekly\n"
        "    decay_half_life_bdays: 8\n"
        "  - series_id: GDP\n"
        "    axis: growth\n"
        "    transform: yoy_pct\n"
        "    frequency_hint: quarterly\n"
    )
    specs = {s.series_id: s for s in load_series_specs(p)}
    assert specs["CLAIMS"].decay_half_life_bdays == 8.0
    assert specs["CLAIMS"].frequency_hint == "weekly"
    # GDP has no explicit override → field stays None, hint drives at runtime
    assert specs["GDP"].decay_half_life_bdays is None
    assert specs["GDP"].frequency_hint == "quarterly"
