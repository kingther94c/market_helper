from __future__ import annotations

"""Re-export contract guard for
`domain.portfolio_monitor.services.security_reference_table`.

The module is a pure pass-through to `common.models.security_reference`
(itself a re-export of `portfolio.security_reference`). The real logic is
covered by `tests/unit/portfolio/test_security_reference.py`. These tests
exist only to lock the public surface so an accidental rename or removal in
the underlying module is caught at the import layer, not at runtime in the
dashboard / pipeline call-sites that depend on the wrapper.
"""

import market_helper.common.models.security_reference as common_security_reference
import market_helper.domain.portfolio_monitor.services.security_reference_table as wrapper


_EXPECTED_PUBLIC_NAMES: tuple[str, ...] = (
    "DEFAULT_SECURITY_REFERENCE_PATH",
    "DEFAULT_SECURITY_UNIVERSE_PATH",
    "PortfolioPositionSnapshot",
    "PortfolioPriceSnapshot",
    "SecurityMapping",
    "SecurityReference",
    "SecurityReferenceTable",
    "SecurityUniverseRow",
    "SecurityUniverseTable",
    "build_security_reference_table",
    "build_price_lookup",
    "export_security_reference_csv",
    "export_security_universe_proposal_csv",
    "join_positions_with_latest_price",
    "now_utc_iso",
    "sync_security_reference_csv",
)


def test_all_expected_public_names_are_exported() -> None:
    missing = [name for name in _EXPECTED_PUBLIC_NAMES if not hasattr(wrapper, name)]
    assert missing == [], f"wrapper module is missing expected re-exports: {missing}"


def test_dunder_all_matches_expected_public_names() -> None:
    assert set(wrapper.__all__) == set(_EXPECTED_PUBLIC_NAMES)


def test_each_reexport_is_the_same_object_as_upstream() -> None:
    # Object-identity check: re-exports must be the canonical symbol, not a
    # shadowed local copy. Catches accidental local redefinition (e.g.
    # someone writes `SecurityReference = ...` in the wrapper module by
    # mistake during a refactor).
    for name in _EXPECTED_PUBLIC_NAMES:
        upstream = getattr(common_security_reference, name)
        local = getattr(wrapper, name)
        assert upstream is local, f"{name} differs between wrapper and upstream"
