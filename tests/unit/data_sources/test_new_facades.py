import pytest

from market_helper.data_sources.fred import download_fred_series_batch
from market_helper.data_sources.ibkr.tws import choose_tws_account
from market_helper.data_sources.yahoo_finance import YahooFinanceClient


def test_ibkr_tws_facade_preserves_choose_account_behavior() -> None:
    assert choose_tws_account(["U1", "U2"], "U2") == "U2"


def test_fred_facade_exports_batch_loader() -> None:
    assert callable(download_fred_series_batch)


def test_yahoo_finance_facade_is_explicit_scaffold() -> None:
    client = YahooFinanceClient()
    with pytest.raises(NotImplementedError):
        client.fetch_price_history("SPY")
