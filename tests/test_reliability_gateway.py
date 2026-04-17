import pytest
from stockpilot.data.adapters import Market
from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter
from stockpilot.data.errors import CoverageEmptyData, DisabledDataSourceError


def test_yfinance_fundamentals_raise_coverage_empty(monkeypatch):
    class FakeTicker:
        info = {}

    adapter = YFinanceAdapter()
    monkeypatch.setattr("stockpilot.data.adapters.yfinance_adapter.yf.Ticker", lambda symbol: FakeTicker())

    with pytest.raises(CoverageEmptyData):
        adapter.get_fundamental_data("AAPL")


def test_unsupported_market_maps_to_disabled_source():
    adapter = AKShareAdapter()
    with pytest.raises(DisabledDataSourceError):
        adapter.get_stock_list(Market.US)
