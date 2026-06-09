"""Monitor EQ currency breakdown — roll the leaf country breakdown up to currency."""

from __future__ import annotations

from market_helper.reporting.risk_html import BreakdownRow, _build_currency_breakdown


def _row(bucket: str, exposure: float) -> BreakdownRow:
    return BreakdownRow(
        bucket=bucket, bucket_label=bucket, parent="EQ",
        exposure_usd=exposure, gross_exposure_usd=abs(exposure),
        dollar_weight=exposure / 1000.0, risk_contribution_estimated=exposure / 100.0,
    )


def test_build_currency_breakdown_aggregates_by_currency():
    rows = [_row("DM-US", 700.0), _row("DM-JP", 200.0), _row("DM-EUME", 100.0),
            _row("EM-CN", 50.0), _row("EM-LATAM", 30.0)]
    out = _build_currency_breakdown(rows)
    by = {r.bucket: r for r in out}
    assert by["USD"].gross_exposure_usd == 700.0
    assert by["JPY"].gross_exposure_usd == 200.0
    assert by["EUR"].gross_exposure_usd == 100.0    # DM-EUME → EUR
    assert by["CNY"].gross_exposure_usd == 50.0
    assert by["Other"].gross_exposure_usd == 30.0   # EM-LATAM → Other
    assert out[0].bucket == "USD"                   # sorted by gross desc
    # risk contribution is carried through (summed), not dropped
    assert by["USD"].risk_contribution_estimated == 7.0


def test_build_currency_breakdown_sums_same_currency_buckets():
    # Two buckets mapping to the same currency must combine.
    rows = [_row("DM-EUME", 100.0), _row("DM-Other DM", 40.0), _row("EM-ASEAN", 10.0)]
    by = {r.bucket: r for r in _build_currency_breakdown(rows)}
    # DM-Other DM + EM-ASEAN both → Other → 50
    assert by["Other"].gross_exposure_usd == 50.0
    assert by["EUR"].gross_exposure_usd == 100.0
