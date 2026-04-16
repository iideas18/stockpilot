"""yfinance data adapter — for US, HK, and international markets.

Ported from TradingAgents' dataflows/ module.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd

from stockpilot.data.adapters import BaseDataAdapter, Market, StockInfo, TimeFrame

logger = logging.getLogger(__name__)


class YFinanceAdapter(BaseDataAdapter):
    """yfinance adapter for US/international market data."""

    name = "yfinance"
    supported_markets = [Market.US, Market.HK, Market.GLOBAL]

    def __init__(self) -> None:
        try:
            import yfinance as yf
            self._yf = yf
        except ImportError:
            raise ImportError("yfinance is required: pip install yfinance")

    def get_stock_list(self, market: Market = Market.US) -> pd.DataFrame:
        raise NotImplementedError("yfinance does not provide stock listings; use search() instead")

    def get_price_history(
        self,
        symbol: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        timeframe: TimeFrame = TimeFrame.DAILY,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """Get historical OHLCV data via yfinance."""
        interval_map = {
            TimeFrame.DAILY: "1d",
            TimeFrame.WEEKLY: "1wk",
            TimeFrame.MONTHLY: "1mo",
            TimeFrame.MIN_1: "1m",
            TimeFrame.MIN_5: "5m",
            TimeFrame.MIN_15: "15m",
            TimeFrame.MIN_30: "30m",
            TimeFrame.MIN_60: "60m",
        }
        interval = interval_map.get(timeframe, "1d")

        ticker = self._yf.Ticker(symbol)
        df = ticker.history(
            start=self._to_date_str(start_date) if start_date else None,
            end=self._to_date_str(end_date) if end_date else None,
            interval=interval,
            auto_adjust=(adjust != "none"),
        )
        return self._normalize_df(df)

    def get_realtime_quote(self, symbol: str) -> dict[str, Any]:
        """Get current quote via yfinance."""
        ticker = self._yf.Ticker(symbol)
        info = ticker.info
        return {
            "symbol": symbol,
            "name": info.get("shortName", ""),
            "price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "change": info.get("regularMarketChange"),
            "change_pct": info.get("regularMarketChangePercent"),
            "volume": info.get("regularMarketVolume"),
            "open": info.get("regularMarketOpen"),
            "high": info.get("regularMarketDayHigh"),
            "low": info.get("regularMarketDayLow"),
            "prev_close": info.get("regularMarketPreviousClose"),
            "market_cap": info.get("marketCap"),
        }

    def get_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Get quotes for multiple tickers."""
        rows = []
        for sym in symbols:
            try:
                rows.append(self.get_realtime_quote(sym))
            except Exception as e:
                logger.warning(f"Failed to get quote for {sym}: {e}")
        return pd.DataFrame(rows)

    def get_fundamental_data(self, symbol: str) -> dict[str, Any]:
        """Get fundamental metrics via yfinance.Ticker.info."""
        info = self._yf.Ticker(symbol).info
        return {
            "symbol": symbol,
            "pe_ratio": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "pb_ratio": info.get("priceToBook"),
            "ps_ratio": info.get("priceToSalesTrailing12Months"),
            "market_cap": info.get("marketCap"),
            "enterprise_value": info.get("enterpriseValue"),
            "dividend_yield": info.get("dividendYield"),
            "beta": info.get("beta"),
            "eps": info.get("trailingEps"),
            "revenue": info.get("totalRevenue"),
            "profit_margin": info.get("profitMargins"),
            "roe": info.get("returnOnEquity"),
            "debt_to_equity": info.get("debtToEquity"),
            "free_cash_flow": info.get("freeCashflow"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
        }

    def get_financial_statements(
        self,
        symbol: str,
        report_type: str = "income",
        period: str = "annual",
    ) -> pd.DataFrame:
        """Get financial statements from yfinance."""
        ticker = self._yf.Ticker(symbol)
        if report_type == "income":
            return ticker.income_stmt if period == "annual" else ticker.quarterly_income_stmt
        elif report_type == "balance":
            return ticker.balance_sheet if period == "annual" else ticker.quarterly_balance_sheet
        elif report_type == "cashflow":
            return ticker.cashflow if period == "annual" else ticker.quarterly_cashflow
        raise ValueError(f"Unknown report_type: {report_type}")

    def get_dividend_history(self, symbol: str) -> pd.DataFrame:
        return self._yf.Ticker(symbol).dividends.reset_index()

    def search(self, keyword: str) -> list[StockInfo]:
        """Search is limited in yfinance; try ticker directly."""
        try:
            info = self._yf.Ticker(keyword).info
            if info.get("shortName"):
                return [StockInfo(
                    symbol=keyword,
                    name=info["shortName"],
                    market=Market.US,
                    industry=info.get("industry", ""),
                    sector=info.get("sector", ""),
                )]
        except Exception:
            pass
        return []

    # ── helpers ──

    @staticmethod
    def _to_date_str(d: str | date | datetime) -> str:
        if isinstance(d, str):
            return d
        return d.strftime("%Y-%m-%d")

    @staticmethod
    def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
        df = df.reset_index()
        col_map = {
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
        df = df.rename(columns=col_map)
        keep = [c for c in ("date", "open", "high", "low", "close", "volume") if c in df.columns]
        return df[keep]
