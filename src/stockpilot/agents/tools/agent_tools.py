"""Agent tools — shared tool functions that LLM agents can invoke.

These tools wrap the data, analysis, and news modules so agents
can access them through LangChain's tool interface.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from typing import Any

from langchain_core.tools import tool

from stockpilot.data.runtime import build_default_data_gateway


def _error_payload(result: Any) -> dict[str, Any] | None:
    """Return an envelope dict if the DataResult carries an error, else None."""
    err = getattr(result, "error", None)
    if err is None:
        return None
    return {
        "data_status": result.to_status_dict(),
        "error": {
            "status": err.status,
            "code": err.code,
            "message": err.message,
            "domain": err.domain,
            "market": err.market,
            "symbol": err.symbol,
        },
        "data": None,
    }


@tool
def get_stock_price_history(
    symbol: str,
    days: int = 90,
    market: str = "a_share",
) -> str:
    """Get historical price data for a stock. Returns OHLCV data as JSON."""
    from stockpilot.data.adapters import Market

    gateway = build_default_data_gateway()

    end = date.today()
    start = end - timedelta(days=days)
    result = gateway.get_price_history(
        symbol, market=Market(market), start_date=start, end_date=end
    )

    err_payload = _error_payload(result)
    if err_payload is not None:
        return json.dumps(err_payload, default=str)

    df = result.data
    if df is None or getattr(df, "empty", True):
        payload = {
            "data_status": result.to_status_dict(),
            "data": [],
        }
        return json.dumps(payload, default=str)

    payload = {
        "data_status": result.to_status_dict(),
        "data": json.loads(df.tail(30).to_json(orient="records", date_format="iso")),
    }
    return json.dumps(payload, default=str)


@tool
def get_stock_fundamentals(symbol: str, market: str = "a_share") -> str:
    """Get fundamental data (PE, PB, market cap) for a stock."""
    from stockpilot.data.adapters import Market

    gateway = build_default_data_gateway()
    result = gateway.get_fundamental_data(symbol, market=Market(market))

    err_payload = _error_payload(result)
    if err_payload is not None:
        return json.dumps(err_payload, default=str)

    payload = {
        "data_status": result.to_status_dict(),
        "data": result.data,
    }
    return json.dumps(payload, default=str)


@tool
def run_technical_analysis(symbol: str, days: int = 120, market: str = "a_share") -> str:
    """Run full technical analysis on a stock and return signals."""
    from stockpilot.data.adapters import Market
    from stockpilot.analysis.signals import generate_signals

    gateway = build_default_data_gateway()

    end = date.today()
    start = end - timedelta(days=days)
    result = gateway.get_price_history(
        symbol, market=Market(market), start_date=start, end_date=end
    )

    err_payload = _error_payload(result)
    if err_payload is not None:
        return json.dumps(err_payload, default=str)

    df = result.data
    if df is None or df.empty:
        return json.dumps(
            {
                "data_status": result.to_status_dict(),
                "data": None,
                "error": f"No data found for {symbol}",
            },
            default=str,
        )

    signals = generate_signals(df)
    signals["signal"] = signals["signal"].value
    payload = {
        "data_status": result.to_status_dict(),
        "data": signals,
    }
    return json.dumps(payload, default=str)


@tool
def get_pattern_analysis(symbol: str, market: str = "a_share") -> str:
    """Detect K-line candlestick patterns for a stock."""
    from stockpilot.data.adapters import Market
    from stockpilot.analysis.patterns import get_pattern_summary

    gateway = build_default_data_gateway()

    end = date.today()
    start = end - timedelta(days=60)
    result = gateway.get_price_history(
        symbol, market=Market(market), start_date=start, end_date=end
    )

    err_payload = _error_payload(result)
    if err_payload is not None:
        return json.dumps(err_payload, default=str)

    df = result.data
    if df is None or df.empty:
        return json.dumps(
            {
                "data_status": result.to_status_dict(),
                "data": None,
                "error": f"No data found for {symbol}",
            },
            default=str,
        )

    summary = get_pattern_summary(df)
    payload = {
        "data_status": result.to_status_dict(),
        "data": summary,
    }
    return json.dumps(payload, default=str)


@tool
def search_stock(keyword: str, market: str = "a_share") -> str:
    """Search for stocks by name or symbol."""
    from stockpilot.data.adapters import Market

    gateway = build_default_data_gateway()
    result = gateway.search(keyword, market=Market(market))

    err_payload = _error_payload(result)
    if err_payload is not None:
        return json.dumps(err_payload, default=str)

    results = result.data or []
    payload = {
        "data_status": result.to_status_dict(),
        "data": [r.model_dump() for r in results[:10]],
    }
    return json.dumps(payload, default=str)


ALL_AGENT_TOOLS = [
    get_stock_price_history,
    get_stock_fundamentals,
    run_technical_analysis,
    get_pattern_analysis,
    search_stock,
]
