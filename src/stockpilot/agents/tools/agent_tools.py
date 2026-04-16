"""Agent tools — shared tool functions that LLM agents can invoke.

These tools wrap the data, analysis, and news modules so agents
can access them through LangChain's tool interface.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import tool


@tool
def get_stock_price_history(
    symbol: str,
    days: int = 90,
    market: str = "a_share",
) -> str:
    """Get historical price data for a stock. Returns OHLCV data as JSON."""
    from stockpilot.data.adapters import Market, TimeFrame
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    dm.register_adapter(YFinanceAdapter())

    end = date.today()
    start = end - timedelta(days=days)
    mkt = Market(market)

    df = dm.get_price_history(symbol, market=mkt, start_date=start, end_date=end)
    return df.tail(30).to_json(orient="records", date_format="iso")


@tool
def get_stock_fundamentals(symbol: str, market: str = "a_share") -> str:
    """Get fundamental data (PE, PB, market cap) for a stock."""
    from stockpilot.data.adapters import Market
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    dm.register_adapter(YFinanceAdapter())

    result = dm.get_fundamental_data(symbol, market=Market(market))
    return json.dumps(result, default=str)


@tool
def run_technical_analysis(symbol: str, days: int = 120) -> str:
    """Run full technical analysis on a stock and return signals."""
    from stockpilot.data.adapters import Market
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.analysis.signals import generate_signals

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)

    end = date.today()
    start = end - timedelta(days=days)
    df = dm.get_price_history(symbol, start_date=start, end_date=end)

    if df.empty:
        return json.dumps({"error": f"No data found for {symbol}"})

    result = generate_signals(df)
    result["signal"] = result["signal"].value
    return json.dumps(result, default=str)


@tool
def get_pattern_analysis(symbol: str) -> str:
    """Detect K-line candlestick patterns for a stock."""
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.analysis.patterns import get_pattern_summary

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)

    end = date.today()
    start = end - timedelta(days=60)
    df = dm.get_price_history(symbol, start_date=start, end_date=end)

    if df.empty:
        return json.dumps({"error": f"No data found for {symbol}"})

    result = get_pattern_summary(df)
    return json.dumps(result, default=str)


@tool
def search_stock(keyword: str) -> str:
    """Search for stocks by name or symbol."""
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    results = dm.search(keyword)
    return json.dumps([r.model_dump() for r in results[:10]], default=str)


ALL_AGENT_TOOLS = [
    get_stock_price_history,
    get_stock_fundamentals,
    run_technical_analysis,
    get_pattern_analysis,
    search_stock,
]
