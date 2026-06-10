"""Option-scan persistence — the scan survives a reload, honestly stamped."""

from __future__ import annotations

from market_helper.application.trade_advisor.option_scan import (
    load_option_scan,
    save_option_scan,
    suggestion_from_dict,
    suggestion_to_dict,
)
from market_helper.trade_advisor.contracts import (
    AuditEntry,
    IdeaAssessment,
    Sizing,
    Suggestion,
)


def _rich_suggestion() -> Suggestion:
    return Suggestion(
        advisor="option", suggestion_id="opt:SPY:cc", as_of="2026-06-10",
        title="COVERED_CALL · SPY", subject="SPY", category="INCOME",
        label="WATCHLIST", decision_tier="T2 · deterministic", score=0.71,
        thesis="Sell the 35d call.", why_now="IV rich vs realized.",
        headline_metrics={"yield": "38%/yr", "IV/RV": "1.31x", "net": "credit 412"},
        drivers=[("yield_or_efficiency", 0.62), ("vrp_ratio", 1.31)],
        audit=[AuditEntry("min_premium", True, "hard", "cleared 1.5x costs")],
        data_mode="live_chain",
        assessment=IdeaAssessment(confidence="medium", actionability="staged",
                                  risk_boundedness="capped", data_quality="live",
                                  notes={"data_quality": "chain: live"}),
        sizing=Sizing(basis="held_lots", max_units=2, capital_at_risk_usd=1500.0),
        body_kind="option_payoff",
        detail={"spot": 590.0, "est_payoff_curve": [[500.0, -9000.0], [600.0, 412.0]]},
    )


def test_suggestion_round_trips_through_dict():
    s = _rich_suggestion()
    back = suggestion_from_dict(suggestion_to_dict(s))
    assert back.suggestion_id == s.suggestion_id
    assert back.assessment == s.assessment            # nested dataclass reconstructed
    assert back.audit == s.audit
    assert back.sizing == s.sizing
    assert back.drivers == [("yield_or_efficiency", 0.62), ("vrp_ratio", 1.31)]  # tuples restored
    assert back.detail["spot"] == 590.0


def test_suggestion_from_dict_ignores_unknown_keys():
    payload = suggestion_to_dict(_rich_suggestion())
    payload["some_future_field"] = "x"                # forward-compat: never crash
    back = suggestion_from_dict(payload)
    assert back.subject == "SPY"


def test_save_and_load_round_trip(tmp_path):
    path = tmp_path / "scan.json"
    save_option_scan(
        [_rich_suggestion()], as_of="2026-06-10", data_mode="live_chain",
        inputs={"symbols": ["SPY", "QQQ"], "use_portfolio": True},
        warnings=["QQQ: no chain"], path=path, saved_at="2026-06-10T09:30:00",
    )
    out = load_option_scan(path)
    assert out is not None
    assert out["saved_at"] == "2026-06-10T09:30:00"   # honest stamp, not regenerated
    assert out["data_mode"] == "live_chain"
    assert out["inputs"]["use_portfolio"] is True
    assert out["warnings"] == ["QQQ: no chain"]
    assert [s.suggestion_id for s in out["suggestions"]] == ["opt:SPY:cc"]


def test_load_missing_and_corrupt_are_none(tmp_path):
    assert load_option_scan(tmp_path / "nope.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_option_scan(bad) is None              # corrupt artifact never breaks the page
