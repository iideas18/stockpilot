from __future__ import annotations

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient

from stockpilot.api import main as api_main
from stockpilot.backtesting.engine import BacktestConfig, BacktestEngine, TradeAction
from stockpilot.data.adapters import BaseDataAdapter, Market
from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
from stockpilot.data.manager import DataManager
from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter


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


def test_patterns_route_serializes_numpy_pattern_strength(monkeypatch):
    class DummyManager:
        def get_price_history(self, symbol, market=None, start_date=None, end_date=None):
            return _sample_price_df()

    def fake_detect_patterns(df):
        enriched = df.copy()
        hammer = np.zeros(len(enriched), dtype=np.int32)
        hammer[-1] = np.int32(100)
        enriched["CDLHAMMER"] = hammer
        return enriched

    monkeypatch.setattr(api_main, "_build_data_manager", lambda: DummyManager())
    monkeypatch.setattr("stockpilot.analysis.patterns.detect_patterns", fake_detect_patterns)

    client = TestClient(api_main.app)
    response = client.post("/api/v1/analysis/patterns", json={"symbol": "AAPL", "market": "us"})

    assert response.status_code == 200
    patterns = response.json()["patterns"]["patterns"]
    assert patterns == [
        {
            "date": "2024-01-04 00:00:00",
            "pattern": "Hammer",
            "signal": "bullish",
            "strength": 100,
        }
    ]


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


def test_data_manager_falls_back_to_secondary_price_adapter():
    class _FailingAdapter(BaseDataAdapter):
        name = "primary"
        supported_markets = [Market.A_SHARE]

        def get_stock_list(self, market=Market.A_SHARE):
            return pd.DataFrame()

        def get_price_history(self, symbol, start_date=None, end_date=None, timeframe=None, adjust="qfq"):
            raise ConnectionError("primary source unavailable")

        def get_realtime_quote(self, symbol):
            return {}

        def get_realtime_quotes(self, symbols):
            return pd.DataFrame()

    class _BackupAdapter(BaseDataAdapter):
        name = "backup"
        supported_markets = [Market.A_SHARE]

        def get_stock_list(self, market=Market.A_SHARE):
            return pd.DataFrame()

        def get_price_history(self, symbol, start_date=None, end_date=None, timeframe=None, adjust="qfq"):
            return pd.DataFrame(
                {
                    "date": ["2024-01-01"],
                    "open": [10.0],
                    "high": [10.5],
                    "low": [9.5],
                    "close": [10.2],
                    "volume": [1000],
                }
            )

        def get_realtime_quote(self, symbol):
            return {}

        def get_realtime_quotes(self, symbols):
            return pd.DataFrame()

    manager = DataManager()
    manager.register_adapter(_FailingAdapter(), priority=True)
    manager.register_adapter(_BackupAdapter())

    df = manager.get_price_history("603799", market=Market.A_SHARE)

    assert not df.empty
    assert float(df["close"].iloc[0]) == 10.2


def test_akshare_adapter_falls_back_to_tencent_history():
    class _FakeAK:
        def __init__(self):
            self.calls = []

        def stock_zh_a_hist(self, **kwargs):
            self.calls.append(("eastmoney", kwargs))
            raise ConnectionError("eastmoney unavailable")

        def stock_zh_a_hist_tx(self, **kwargs):
            self.calls.append(("tencent", kwargs))
            return pd.DataFrame(
                {
                    "date": ["2024-01-01", "2024-01-02"],
                    "open": [10.0, 10.2],
                    "close": [10.1, 10.4],
                    "high": [10.3, 10.5],
                    "low": [9.9, 10.1],
                    "amount": [1000000, 1200000],
                }
            )

        def stock_zh_a_daily(self, **kwargs):
            self.calls.append(("sina", kwargs))
            raise AssertionError("Sina fallback should not be used when Tencent succeeds")

    adapter = object.__new__(AKShareAdapter)
    adapter._ak = _FakeAK()

    df = adapter.get_price_history("603799", start_date="2024-01-01", end_date="2024-01-02")

    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume", "amount"]
    assert df["volume"].isna().all()
    assert float(df["close"].iloc[-1]) == 10.4
    assert adapter._ak.calls[1][0] == "tencent"
    assert adapter._ak.calls[1][1]["symbol"] == "sh603799"


def test_akshare_adapter_falls_back_to_sina_history_after_tencent_failure():
    class _FakeAK:
        def __init__(self):
            self.calls = []

        def stock_zh_a_hist(self, **kwargs):
            self.calls.append(("eastmoney", kwargs))
            raise ConnectionError("eastmoney unavailable")

        def stock_zh_a_hist_tx(self, **kwargs):
            self.calls.append(("tencent", kwargs))
            raise ConnectionError("tencent unavailable")

        def stock_zh_a_daily(self, **kwargs):
            self.calls.append(("sina", kwargs))
            return pd.DataFrame(
                {
                    "date": ["2024-01-01", "2024-01-02"],
                    "open": [10.0, 10.2],
                    "high": [10.3, 10.5],
                    "low": [9.9, 10.1],
                    "close": [10.1, 10.4],
                    "volume": [1000, 1200],
                    "amount": [1000000, 1200000],
                    "outstanding_share": [1.0, 1.0],
                    "turnover": [0.01, 0.02],
                }
            )

    adapter = object.__new__(AKShareAdapter)
    adapter._ak = _FakeAK()

    df = adapter.get_price_history("000001", start_date="2024-01-01", end_date="2024-01-02")

    assert float(df["volume"].iloc[-1]) == 1200.0
    assert float(df["close"].iloc[-1]) == 10.4
    assert adapter._ak.calls[-1][0] == "sina"
    assert adapter._ak.calls[-1][1]["symbol"] == "sz000001"


def test_yfinance_adapter_normalizes_a_share_symbols():
    assert YFinanceAdapter._normalize_symbol("603799") == "603799.SS"
    assert YFinanceAdapter._normalize_symbol("000001") == "000001.SZ"
    assert YFinanceAdapter._normalize_symbol("AAPL") == "AAPL"
    assert YFinanceAdapter._normalize_symbol("600000.ss") == "600000.SS"
