from __future__ import annotations

import pandas as pd
from fastapi.testclient import TestClient

from stockpilot.api import main as api_main
from stockpilot.backtesting.engine import BacktestConfig, BacktestEngine, TradeAction
from stockpilot.data.adapters import BaseDataAdapter, Market
from stockpilot.data.manager import DataManager


def _sample_price_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=4, freq="D"),
            "open": [100.0, 102.0, 101.0, 99.0],
            "high": [101.0, 103.0, 102.0, 100.0],
            "low": [99.0, 101.0, 100.0, 98.0],
            "close": [100.0, 102.0, 101.0, 99.0],
            "volume": [1000, 1100, 1050, 1200],
        }
    )


def test_chart_data_returns_indicator_scores(monkeypatch):
    calls: list[tuple[str, object]] = []

    class DummyManager:
        def get_price_history(self, symbol, market=None, start_date=None, end_date=None):
            calls.append((symbol, market))
            return _sample_price_df()

    def fake_calculate_all_indicators(df):
        enriched = df.copy()
        ma_5 = [None] + [100.5] * max(len(enriched) - 1, 0)
        rsi_12 = [50.0] * len(enriched)
        if rsi_12:
            rsi_12[-1] = 62.0
        enriched["ma_5"] = ma_5
        enriched["rsi_12"] = rsi_12
        return enriched

    def fake_pattern_summary(_df, lookback=5):
        return {
            "total_patterns": 1,
            "bullish_count": 1,
            "bearish_count": 0,
            "bullish_score": 1.0,
            "patterns": [{"date": "2024-01-04", "pattern": "Hammer", "signal": "bullish", "strength": 100}],
        }

    monkeypatch.setattr(api_main, "_build_data_manager", lambda: DummyManager())
    monkeypatch.setattr("stockpilot.analysis.indicators.calculate_all_indicators", fake_calculate_all_indicators)
    monkeypatch.setattr("stockpilot.analysis.signals.calculate_all_indicators", fake_calculate_all_indicators)
    monkeypatch.setattr("stockpilot.analysis.signals.get_pattern_summary", fake_pattern_summary)

    client = TestClient(api_main.app)
    response = client.get("/api/v1/stocks/AAPL/chart-data?days=30&market=us")

    assert response.status_code == 200
    payload = response.json()
    assert payload["symbol"] == "AAPL"
    assert payload["indicator_scores"]["rsi"] == 0.5
    assert calls == [("AAPL", "us")]


def test_patterns_route_uses_requested_market(monkeypatch):
    calls: list[tuple[str, object]] = []

    class DummyManager:
        def get_price_history(self, symbol, market=None, start_date=None, end_date=None):
            calls.append((symbol, market))
            return _sample_price_df()

    monkeypatch.setattr(api_main, "_build_data_manager", lambda: DummyManager())
    monkeypatch.setattr(
        "stockpilot.analysis.patterns.get_pattern_summary",
        lambda df: {"total_patterns": 0, "bullish_count": 0, "bearish_count": 0, "bullish_score": 0.5, "patterns": []},
    )

    client = TestClient(api_main.app)
    response = client.post("/api/v1/analysis/patterns", json={"symbol": "AAPL", "market": "us"})

    assert response.status_code == 200
    assert response.json()["patterns"]["patterns"] == []
    assert calls == [("AAPL", "us")]


def test_portfolio_optimize_supports_requested_market(monkeypatch):
    calls: list[tuple[str, object]] = []

    class DummyManager:
        def get_price_history(self, symbol, market=None, start_date=None, end_date=None):
            calls.append((symbol, market))
            return _sample_price_df()

    monkeypatch.setattr(api_main, "_build_data_manager", lambda: DummyManager())

    client = TestClient(api_main.app)
    response = client.post(
        "/api/v1/portfolio/optimize",
        json={
            "symbols": ["AAPL", "MSFT"],
            "method": "equal_weight",
            "market": "us",
            "capital": 500000,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["loaded_symbols"] == ["AAPL", "MSFT"]
    assert calls == [("AAPL", "us"), ("MSFT", "us")]


def test_backtest_invalid_strategy_returns_400(monkeypatch):
    class DummyManager:
        def get_price_history(self, symbol, market=None, start_date=None, end_date=None):
            return _sample_price_df()

    monkeypatch.setattr(api_main, "_build_data_manager", lambda: DummyManager())
    monkeypatch.setattr("stockpilot.analysis.indicators.calculate_all_indicators", lambda df: df)

    client = TestClient(api_main.app)
    response = client.post(
        "/api/v1/backtest/run",
        json={
            "symbol": "AAPL",
            "market": "us",
            "strategy": "does_not_exist",
            "start_date": "2024-01-01",
            "end_date": "2024-01-10",
            "initial_capital": 100000,
        },
    )

    assert response.status_code == 400
    assert "Unknown strategy" in response.json()["detail"]


def test_invalid_market_is_rejected():
    client = TestClient(api_main.app)
    response = client.get("/api/v1/stocks/AAPL/chart-data?market=not-a-market")
    assert response.status_code == 422


def test_backtest_engine_reports_win_rate():
    engine = BacktestEngine(BacktestConfig(initial_capital=100000))
    engine.add_data("TEST", _sample_price_df())

    def strategy(current_date, data, portfolio):
        price = float(data["TEST"]["close"])
        if current_date == "2024-01-01":
            return [TradeAction(current_date, "TEST", "buy", 100, price, "entry-1")]
        if current_date == "2024-01-02":
            return [TradeAction(current_date, "TEST", "sell", 100, price, "exit-win")]
        if current_date == "2024-01-03":
            return [TradeAction(current_date, "TEST", "buy", 100, price, "entry-2")]
        if current_date == "2024-01-04":
            return [TradeAction(current_date, "TEST", "sell", 100, price, "exit-loss")]
        return []

    result = engine.run(strategy)

    assert result.metrics.total_trades == 4
    assert result.metrics.winning_trades == 1
    assert result.metrics.losing_trades == 1
    assert result.metrics.win_rate == 0.5


def test_data_manager_cache_separates_markets():
    class _Adapter(BaseDataAdapter):
        def __init__(self, name, market, close):
            self.name = name
            self.supported_markets = [market]
            self._close = close

        def get_stock_list(self, market=Market.A_SHARE):
            return pd.DataFrame()

        def get_price_history(self, symbol, start_date=None, end_date=None, timeframe=None, adjust="qfq"):
            return pd.DataFrame(
                {
                    "date": ["2024-01-01"],
                    "open": [self._close],
                    "high": [self._close],
                    "low": [self._close],
                    "close": [self._close],
                    "volume": [100],
                }
            )

        def get_realtime_quote(self, symbol):
            return {}

        def get_realtime_quotes(self, symbols):
            return pd.DataFrame()

    manager = DataManager()
    manager.register_adapter(_Adapter("a-share", Market.A_SHARE, 10.0), priority=True)
    manager.register_adapter(_Adapter("us", Market.US, 20.0), priority=True)

    a_share = manager.get_price_history("TEST", market=Market.A_SHARE)
    us = manager.get_price_history("TEST", market=Market.US)

    assert float(a_share["close"].iloc[0]) == 10.0
    assert float(us["close"].iloc[0]) == 20.0
