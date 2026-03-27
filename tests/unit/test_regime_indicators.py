from market_helper.regimes.indicators import (
    compute_factor_snapshots,
    cumulative_return,
    rolling_mean,
    rolling_percentile,
    rolling_zscore,
)


def test_rolling_mean_and_percentile_behaviour() -> None:
    values = [1.0, 2.0, 3.0, 4.0]
    assert rolling_mean(values, 2) == [1.0, 1.5, 2.5, 3.5]
    pct = rolling_percentile(values, 3)
    assert pct[0] == 1.0
    assert 0.66 <= pct[2] <= 1.0


def test_rolling_zscore_defaults_to_zero_for_flat_series() -> None:
    z = rolling_zscore([2.0, 2.0, 2.0], 3)
    assert z == [0.0, 0.0, 0.0]


def test_cumulative_return_matches_manual_compound() -> None:
    result = cumulative_return([0.10, -0.05, 0.02], lookback=3)
    assert abs(result[-1] - ((1.10 * 0.95 * 1.02) - 1.0)) < 1e-9


def test_compute_factor_snapshots_outputs_expected_shape() -> None:
    n = 80
    snapshots = compute_factor_snapshots(
        dates=[f"2026-01-{idx+1:02d}" for idx in range(n)],
        vix=[18 + (idx % 3) for idx in range(n)],
        move=[100 + (idx % 4) for idx in range(n)],
        hy_oas=[3.5 + (idx % 5) * 0.01 for idx in range(n)],
        y2=[0.03 + idx * 0.0001 for idx in range(n)],
        y10=[0.04 + idx * 0.0001 for idx in range(n)],
        eq_returns=[0.001 * ((idx % 7) - 3) for idx in range(n)],
        fi_returns=[0.0005 * ((idx % 5) - 2) for idx in range(n)],
    )
    assert len(snapshots) == n
    assert 0.0 <= snapshots[-1].vol <= 1.0
    assert -1.0 <= snapshots[-1].rates <= 1.0
