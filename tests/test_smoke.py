"""Basic smoke tests for StockPilot modules."""

import pytest


def test_imports():
    """Test that all main modules can be imported."""
    from stockpilot import __version__
    assert __version__ == "0.1.0"

    from stockpilot.config import get_settings
    settings = get_settings()
    assert settings.app_name == "StockPilot"

    from stockpilot.data.adapters import BaseDataAdapter, Market, TimeFrame
    assert Market.A_SHARE == "a_share"
    assert TimeFrame.DAILY == "daily"

    from stockpilot.data.cache import MemoryCache, DataCache
    cache = MemoryCache()
    cache.set("test_key", "test_value", ttl=60)
    assert cache.get("test_key") == "test_value"

    from stockpilot.data.models import Base, StockDaily, StockInfo, AgentAnalysis


def test_data_manager():
    """Test DataManager initialization and adapter registration."""
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters import Market

    dm = DataManager()
    assert dm.available_adapters == []

    # Adapters are lazy-loaded; just test the manager logic
    assert dm.market_routing == {}


def test_indicators_import():
    """Test that analysis indicators module loads."""
    from stockpilot.analysis.indicators import (
        calculate_ma, calculate_ema, calculate_macd, calculate_rsi,
        calculate_kdj, calculate_bollinger, calculate_atr, calculate_cci,
        calculate_obv, calculate_sar, calculate_adx, calculate_dmi,
        calculate_all_indicators,
    )
    import pandas as pd
    import numpy as np

    # Test with synthetic data
    close = pd.Series(np.random.randn(100).cumsum() + 50)
    ma = calculate_ma(close, 10)
    assert len(ma) == 100
    assert ma.isna().sum() == 9  # First 9 values should be NaN

    rsi = calculate_rsi(close, 14)
    assert len(rsi) == 100


def test_patterns_import():
    """Test pattern detection module."""
    from stockpilot.analysis.patterns import CANDLESTICK_PATTERNS
    assert len(CANDLESTICK_PATTERNS) == 61


def test_signals_import():
    """Test signal generation module."""
    from stockpilot.analysis.signals import Signal, score_indicators
    assert Signal.STRONG_BUY == "strong_buy"
    assert Signal.HOLD == "hold"


def test_agent_personas():
    """Test investor persona definitions."""
    from stockpilot.agents.personas.investors import PERSONAS, get_agents_list
    assert len(PERSONAS) == 19  # 13 investors + 6 specialist analysts
    assert "warren_buffett" in PERSONAS
    assert "charlie_munger" in PERSONAS
    assert "cathie_wood" in PERSONAS
    assert "michael_burry" in PERSONAS
    assert "nassim_taleb" in PERSONAS  # New in 2026-04 update
    assert "technical_analyst" in PERSONAS
    assert "fundamentals_analyst" in PERSONAS
    assert "growth_analyst" in PERSONAS
    assert "valuation_analyst" in PERSONAS
    assert "news_sentiment_analyst" in PERSONAS
    assert "sentiment_analyst" in PERSONAS

    agents_list = get_agents_list()
    assert len(agents_list) == 19
    assert agents_list[0]["key"] == "warren_buffett"


def test_news_aggregator():
    """Test news aggregator initialization."""
    from stockpilot.news.aggregator import NewsAggregator, PLATFORMS
    agg = NewsAggregator(platforms=["hackernews"])
    assert "hackernews" in agg.platforms


def test_news_aggregator_reads_platforms_from_env(monkeypatch):
    """News aggregator should read default platforms from env-backed settings."""
    from stockpilot.config import get_settings
    from stockpilot.news.aggregator import NewsAggregator

    monkeypatch.delenv("STOCKPILOT_NEWS_PLATFORMS", raising=False)
    monkeypatch.setenv("NEWS_PLATFORMS", "hackernews, reddit")
    get_settings.cache_clear()
    try:
        agg = NewsAggregator()
        assert agg.platforms == ["hackernews", "reddit_finance"]
    finally:
        get_settings.cache_clear()


def test_news_settings_parse_comma_separated_env(monkeypatch):
    """Settings loader should accept comma-separated env values for news platforms."""
    from stockpilot.config import get_settings

    monkeypatch.delenv("STOCKPILOT_NEWS_PLATFORMS", raising=False)
    monkeypatch.setenv("NEWS_PLATFORMS", "hackernews, reddit")
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.news.platforms == ["hackernews", "reddit_finance"]
    finally:
        get_settings.cache_clear()


def test_news_aggregator_explicit_platforms_override_env(monkeypatch):
    """Explicit platforms should win over env defaults."""
    from stockpilot.config import get_settings
    from stockpilot.news.aggregator import NewsAggregator

    monkeypatch.setenv("NEWS_PLATFORMS", "weibo")
    get_settings.cache_clear()
    try:
        agg = NewsAggregator(platforms=["reddit"])
        assert agg.platforms == ["reddit_finance"]
    finally:
        get_settings.cache_clear()


def test_trading_engine():
    """Test trading engine components."""
    from stockpilot.trading.engine import (
        EventBus, EventType, Event, BaseStrategy,
        PaperTradingExecutor, TradingEngine,
    )

    engine = TradingEngine(initial_capital=100000, mode="paper")
    assert engine.executor.capital == 100000

    summary = engine.get_portfolio_summary()
    assert summary["capital"] == 100000
    assert summary["total_trades"] == 0


def test_backtesting_engine():
    """Test backtesting engine."""
    from stockpilot.backtesting.engine import BacktestConfig, BacktestEngine, BacktestResult
    config = BacktestConfig(initial_capital=500000)
    engine = BacktestEngine(config)
    assert engine.config.initial_capital == 500000


def test_notification_dispatcher():
    """Test notification dispatcher init."""
    from stockpilot.notifications.dispatcher import NotificationDispatcher
    dispatcher = NotificationDispatcher()
    assert dispatcher is not None


def test_scheduler():
    """Test scheduler."""
    from stockpilot.scheduler.runner import Scheduler, create_default_scheduler
    scheduler = create_default_scheduler()
    status = scheduler.get_status()
    assert len(status) == 4  # 4 default jobs


def test_config_settings():
    """Test settings loading."""
    from stockpilot.config import get_settings
    s = get_settings()
    assert s.data.primary_source == "akshare"
    assert s.llm.default_provider == "openai"
    assert s.trading.mode == "paper"


def test_llm_providers():
    """Test LLM provider registry."""
    from stockpilot.agents.llm.providers import SUPPORTED_MODELS, get_supported_models
    models = get_supported_models()
    assert len(models) >= 13
    providers = {m["provider"] for m in models}
    assert "openai" in providers
    assert "anthropic" in providers
    assert "deepseek" in providers
    assert "xai" in providers
    assert "google" in providers
    assert "openrouter" in providers


def test_stats_tracking():
    """Test LLM stats callback handler."""
    from stockpilot.agents.stats import StatsCallbackHandler, get_global_stats
    handler = StatsCallbackHandler()
    assert handler.get_stats()["llm_calls"] == 0
    handler.on_llm_start({}, ["test"])
    assert handler.get_stats()["llm_calls"] == 1
    handler.on_tool_start({}, "test")
    assert handler.get_stats()["tool_calls"] == 1
    handler.reset()
    assert handler.get_stats()["llm_calls"] == 0

    global_stats = get_global_stats()
    assert global_stats is not None


def test_memory_system():
    """Test financial memory with BM25 retrieval."""
    import tempfile, os
    from stockpilot.agents.memory import FinancialSituationMemory

    with tempfile.TemporaryDirectory() as tmpdir:
        db = os.path.join(tmpdir, "test_memory.db")
        mem = FinancialSituationMemory(name="test", db_path=db)
        assert mem.count() == 0

        mem.add_analysis(
            ticker="000001",
            market="a_share",
            analysis_summary="RSI oversold, MACD bullish crossover",
            recommendation="BUY with moderate confidence",
            signal="buy",
            score=0.72,
        )
        assert mem.count() == 1

        results = mem.recall_for_ticker("000001", n_matches=5)
        assert len(results) >= 1
        assert results[0]["recommendation"] == "BUY with moderate confidence"

        results2 = mem.recall("RSI oversold", n_matches=3)
        assert len(results2) >= 1

        mem.clear()
        assert mem.count() == 0


def test_risk_debate_imports():
    """Test risk management debate system imports."""
    from stockpilot.agents.risk_mgmt.debaters import (
        run_risk_debate,
        AGGRESSIVE_SYSTEM,
        CONSERVATIVE_SYSTEM,
        NEUTRAL_SYSTEM,
        JUDGE_SYSTEM,
    )
    assert "Aggressive" in AGGRESSIVE_SYSTEM
    assert "Conservative" in CONSERVATIVE_SYSTEM
    assert "Neutral" in NEUTRAL_SYSTEM
    assert "Risk Level" in JUDGE_SYSTEM


def test_cli_commands():
    """Test CLI commands are registered."""
    from stockpilot.cli import app
    from typer.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "StockPilot" in result.output

    # Check all commands are registered
    from click import Group
    command_names = [cmd for cmd in app.registered_commands]
    assert len(command_names) >= 7  # analyze, search, news, serve, version, agent, backtest


def test_donchian_channels():
    """Test Donchian channels added for Turtle strategy."""
    import pandas as pd
    import numpy as np
    from stockpilot.analysis.indicators import calculate_all_indicators

    n = 60
    df = pd.DataFrame({
        "open": np.random.uniform(10, 20, n),
        "high": np.random.uniform(15, 25, n),
        "low": np.random.uniform(5, 15, n),
        "close": np.random.uniform(10, 20, n),
        "volume": np.random.randint(1000, 10000, n),
    })
    result = calculate_all_indicators(df)
    assert "high_20" in result.columns
    assert "low_10" in result.columns
    assert "high_55" in result.columns
    assert "low_20" in result.columns
    # After 20 periods, high_20 should have values
    assert not pd.isna(result["high_20"].iloc[-1])


def test_strategy_library():
    """Test strategy library."""
    from stockpilot.trading.strategies.library import (
        STRATEGIES, get_strategy, list_strategies
    )
    strats = list_strategies()
    assert len(strats) >= 6
    types = {s["type"] for s in strats}
    assert "trend" in types
    assert "breakout" in types
    assert "mean_reversion" in types

    # All strategies are callable
    for key, entry in STRATEGIES.items():
        fn = get_strategy(key)
        assert fn is not None
        assert callable(fn)

    assert get_strategy("nonexistent") is None


def test_portfolio_optimizer():
    """Test portfolio optimization."""
    import numpy as np
    import pandas as pd
    from stockpilot.analysis.portfolio import PortfolioOptimizer

    np.random.seed(42)
    opt = PortfolioOptimizer()

    for sym in ["A", "B", "C"]:
        prices = pd.Series(np.cumsum(np.random.randn(100)) + 100)
        opt.add_returns(sym, prices)

    assert len(opt.symbols) == 3

    # Equal weight
    eq = opt.equal_weight()
    assert abs(sum(eq.weights.values()) - 1.0) < 1e-6
    assert all(abs(w - 1/3) < 1e-6 for w in eq.weights.values())

    # Max Sharpe
    ms = opt.max_sharpe(n_portfolios=500)
    assert abs(sum(ms.weights.values()) - 1.0) < 1e-6

    # Risk parity
    rp = opt.risk_parity()
    assert abs(sum(rp.weights.values()) - 1.0) < 1e-6

    # Min variance
    mv = opt.min_variance()
    assert abs(sum(mv.weights.values()) - 1.0) < 1e-6


def test_web_dashboard():
    """Test web dashboard is served correctly."""
    from fastapi.testclient import TestClient
    from stockpilot.api.main import app

    client = TestClient(app)

    # Dashboard page
    res = client.get("/")
    assert res.status_code == 200
    assert "StockPilot" in res.text
    assert "对比实验室" in res.text

    # API endpoints
    res = client.get("/api/v1/strategies")
    assert res.status_code == 200
    data = res.json()
    assert len(data["strategies"]) >= 6

    res = client.get("/api/v1/personas")
    assert res.status_code == 200
    data = res.json()
    assert len(data["personas"]) >= 19

    # Static files
    res = client.get("/static/css/app.css")
    assert res.status_code == 200
    assert "nav-item" in res.text

    res = client.get("/static/js/app.js")
    assert res.status_code == 200
    assert "navigateTo" in res.text
    assert "formatApiError" in res.text
    assert "consumeDataStatus" in res.text
    assert "retry_after_seconds" in res.text
    assert "dedupeKey" in res.text

    res = client.get("/static/js/analysis.js")
    assert res.status_code == 200
    assert ("formatApiError(" in res.text) or ("consumeDataStatus(" in res.text)

    # Route registration for interactive web APIs
    route_paths = {route.path for route in app.routes}
    assert "/api/v1/compare/symbols" in route_paths
    assert "/api/v1/backtest/compare" in route_paths
    assert "/api/v1/portfolio/optimize" in route_paths


def test_interactive_web_api_routes(monkeypatch):
    """Test compare/backtest/portfolio APIs with stubbed data."""
    import numpy as np
    import pandas as pd
    from fastapi.testclient import TestClient
    from stockpilot.api import main as api_main
    import stockpilot.data.manager as data_manager_module

    class DummyManager:
        def register_adapter(self, adapter, priority=False):
            return None

        def get_price_history(self, symbol, market=None, start_date=None, end_date=None):
            base = {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0}.get(symbol, 15.0)
            dates = pd.date_range("2024-01-01", periods=90, freq="D")
            trend = np.linspace(0, 3, len(dates))
            noise = np.sin(np.linspace(0, 6, len(dates))) * 0.5
            close = base + trend + noise
            return pd.DataFrame({
                "date": dates,
                "open": close - 0.2,
                "high": close + 0.4,
                "low": close - 0.5,
                "close": close,
                "volume": np.linspace(1000, 5000, len(dates)),
            })

    def fake_build_data_manager():
        return DummyManager()

    def fake_run_backtest_job(**kwargs):
        dates = pd.date_range("2024-01-01", periods=30, freq="D").strftime("%Y-%m-%d").tolist()
        equity = [kwargs["initial_capital"] * (1 + i * 0.01) for i in range(len(dates))]
        return {
            "symbol": kwargs["symbol"],
            "strategy": kwargs["strategy"],
            "metrics": {
                "total_return_pct": 12.0,
                "annual_return_pct": 18.0,
                "sharpe_ratio": 1.2,
                "max_drawdown_pct": 5.0,
                "win_rate": 0.55,
                "total_trades": 8,
                "final_capital": equity[-1],
            },
            "equity_curve": equity,
            "dates": dates,
            "trades": [],
        }

    monkeypatch.setattr(api_main, "_build_data_manager", fake_build_data_manager)
    monkeypatch.setattr(api_main, "_run_backtest_job", fake_run_backtest_job)
    monkeypatch.setattr(data_manager_module, "DataManager", DummyManager)

    client = TestClient(api_main.app)

    res = client.post("/api/v1/compare/symbols", json={
        "symbols": ["AAA", "BBB"],
        "market": "us",
        "days": 60,
    })
    assert res.status_code == 200
    data = res.json()
    assert len(data["series"]) == 2
    assert {item["symbol"] for item in data["summaries"]} == {"AAA", "BBB"}

    res = client.post("/api/v1/backtest/compare", json={
        "runs": [
            {"symbol": "AAA", "strategy": "ma_crossover", "market": "us"},
            {"symbol": "BBB", "strategy": "turtle", "market": "us"},
        ],
        "days": 120,
        "initial_capital": 100000,
    })
    assert res.status_code == 200
    data = res.json()
    assert len(data["runs"]) == 2
    assert data["runs"][0]["metrics"]["total_trades"] == 8

    res = client.post("/api/v1/portfolio/optimize", json={
        "symbols": ["AAA", "BBB", "CCC"],
        "method": "max_sharpe",
        "market": "us",
        "days": 120,
        "capital": 100000,
        "risk_free_rate": 0.02,
    })
    assert res.status_code == 200
    data = res.json()
    assert set(data["weights"]) == {"AAA", "BBB", "CCC"}
    assert len(data["loaded_symbols"]) == 3


def test_compare_symbols_handles_upstream_failures(monkeypatch):
    """Compare route should return 503 instead of leaking upstream exceptions."""
    from fastapi.testclient import TestClient
    from stockpilot.api import main as api_main

    class FailingManager:
        def get_price_history(self, symbol, market=None, start_date=None, end_date=None):
            raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(api_main, "_build_data_manager", lambda: FailingManager())

    client = TestClient(api_main.app)
    res = client.post("/api/v1/compare/symbols", json={
        "symbols": ["AAA", "BBB"],
        "market": "us",
        "days": 60,
    })

    assert res.status_code == 503
    assert res.json()["detail"] == "Data source unavailable for one or more requested symbols"


def test_backtest_compare_handles_upstream_failures(monkeypatch):
    """Backtest compare should surface upstream data failures as 503."""
    from fastapi.testclient import TestClient
    from stockpilot.api import main as api_main

    class FailingManager:
        def get_price_history(self, symbol, market=None, start_date=None, end_date=None):
            raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(api_main, "_build_data_manager", lambda: FailingManager())

    client = TestClient(api_main.app)
    res = client.post("/api/v1/backtest/compare", json={
        "runs": [
            {"symbol": "AAA", "strategy": "ma_crossover", "market": "us"},
        ],
        "days": 120,
        "initial_capital": 100000,
    })

    assert res.status_code == 503
    assert res.json()["detail"].startswith("Data source unavailable for AAA:")
