"""MCP Server — expose StockPilot tools via Model Context Protocol.

Ported from TrendRadar's mcp_server/ using FastMCP 2.0.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

mcp = FastMCP("StockPilot", instructions="AI-powered quantitative investment platform")


@mcp.tool()
def stock_price(symbol: str, days: int = 30, market: str = "a_share") -> str:
    """Get historical price data for a stock."""
    from stockpilot.data.adapters import Market
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    dm.register_adapter(YFinanceAdapter())
    end = date.today()
    start = end - timedelta(days=days)
    df = dm.get_price_history(symbol, market=Market(market), start_date=start, end_date=end)
    return df.tail(20).to_string()


@mcp.tool()
def stock_analysis(symbol: str) -> str:
    """Run full technical analysis on a stock and return buy/sell signals."""
    from stockpilot.data.adapters import Market
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.analysis.signals import generate_signals

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    end = date.today()
    start = end - timedelta(days=120)
    df = dm.get_price_history(symbol, start_date=start, end_date=end)
    if df.empty:
        return f"No data found for {symbol}"
    result = generate_signals(df)
    result["signal"] = result["signal"].value
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def stock_fundamentals(symbol: str, market: str = "a_share") -> str:
    """Get fundamental data (PE, PB, market cap) for a stock."""
    from stockpilot.data.adapters import Market
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter
    from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    dm.register_adapter(YFinanceAdapter())
    result = dm.get_fundamental_data(symbol, market=Market(market))
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def stock_search(keyword: str) -> str:
    """Search for stocks by name or symbol."""
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    results = dm.search(keyword)
    return "\n".join(f"{r.symbol} - {r.name}" for r in results[:10])


@mcp.tool()
def trending_news(platform: str = "hackernews") -> str:
    """Get trending financial news from various platforms."""
    from stockpilot.news.aggregator import NewsAggregator
    agg = NewsAggregator(platforms=[platform])
    items = agg.fetch_all()
    return "\n".join(f"[{i.source}] {i.title} (score: {i.hot_score})" for i in items[:15])


@mcp.tool()
def portfolio_status() -> str:
    """Get current paper trading portfolio status."""
    return json.dumps({
        "status": "Paper trading not active. Use the API to start a trading session.",
    })


def main():
    """Run the MCP server."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
