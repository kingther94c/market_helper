from market_helper.regime_rulebook import combine_views, score_macro, score_market


def test_macro_overheating_signal():
    macro = {
        "gdp_nowcast_delta": 0.5,
        "payrolls_3m_avg_delta": 50000,
        "unemployment_rate_delta": -0.1,
        "ism_mfg_level": 53,
        "cpi_yoy_minus_target": 1.0,
        "core_cpi_3m_annualized_delta": 0.2,
        "wage_growth_3m_delta": 0.1,
        "5y5y_infl_exp_delta": 0.05,
    }
    macro_scores = score_macro(macro)
    result = combine_views(macro_scores, None)
    assert result["regime"] == "Overheating"


def test_market_stagflation_signal():
    one_week = {
        "SPY": -0.02,
        "IWM_vs_SPY": -0.01,
        "VWO_vs_VEA": -0.005,
        "XLY_vs_XLP": -0.02,
        "COPX": 0.03,
        "USO": 0.04,
        "TIP_vs_IEF": 0.01,
        "TLT": -0.03,
        "HYG_vs_LQD": -0.01,
    }
    market_scores = score_market(one_week)
    result = combine_views(None, market_scores)
    assert result["regime"] == "Stagflation"
    assert result["risk_tag"] == "Risk Off"
