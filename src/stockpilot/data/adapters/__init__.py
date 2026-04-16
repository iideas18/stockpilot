"""Abstract base class for all data adapters.

Every data source (AKShare, EastMoney, yfinance, etc.) implements this interface
so the DataManager can route requests transparently.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from enum import Enum
from typing import Any

import pandas as pd
from pydantic import BaseModel


class Market(str, Enum):
    A_SHARE = "a_share"
    US = "us"
    HK = "hk"
    GLOBAL = "global"


class TimeFrame(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    MIN_1 = "1min"
    MIN_5 = "5min"
    MIN_15 = "15min"
    MIN_30 = "30min"
    MIN_60 = "60min"


class StockInfo(BaseModel):
    """Basic stock information."""
    symbol: str
    name: str
    market: Market
    industry: str = ""
    sector: str = ""
    list_date: date | None = None
    total_shares: float | None = None
    circulating_shares: float | None = None


class BaseDataAdapter(ABC):
    """Abstract interface that all data adapters must implement."""

    name: str = "base"
    supported_markets: list[Market] = []

    @abstractmethod
    def get_stock_list(self, market: Market = Market.A_SHARE) -> pd.DataFrame:
        """Get list of all stocks in a market.

        Returns DataFrame with columns: symbol, name, industry, sector, list_date
        """
        ...

    @abstractmethod
    def get_price_history(
        self,
        symbol: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        timeframe: TimeFrame = TimeFrame.DAILY,
        adjust: str = "qfq",  # qfq=前复权, hfq=后复权, none=不复权
    ) -> pd.DataFrame:
        """Get historical OHLCV price data.

        Returns DataFrame with columns: date, open, high, low, close, volume, amount
        """
        ...

    @abstractmethod
    def get_realtime_quote(self, symbol: str) -> dict[str, Any]:
        """Get real-time quote for a single stock.

        Returns dict with keys: symbol, name, price, change, change_pct, volume,
                                amount, open, high, low, prev_close, timestamp
        """
        ...

    @abstractmethod
    def get_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Get real-time quotes for multiple stocks."""
        ...

    def get_fundamental_data(self, symbol: str) -> dict[str, Any]:
        """Get fundamental data (PE, PB, market cap, etc.). Optional."""
        raise NotImplementedError(f"{self.name} does not support fundamental data")

    def get_financial_statements(
        self,
        symbol: str,
        report_type: str = "income",  # income | balance | cashflow
        period: str = "annual",  # annual | quarterly
    ) -> pd.DataFrame:
        """Get financial statements. Optional."""
        raise NotImplementedError(f"{self.name} does not support financial statements")

    def get_dividend_history(self, symbol: str) -> pd.DataFrame:
        """Get dividend history. Optional."""
        raise NotImplementedError(f"{self.name} does not support dividend history")

    def get_industry_data(self, market: Market = Market.A_SHARE) -> pd.DataFrame:
        """Get industry/sector classification. Optional."""
        raise NotImplementedError(f"{self.name} does not support industry data")

    def get_index_data(
        self,
        symbol: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> pd.DataFrame:
        """Get index data (e.g., 上证指数, 沪深300). Optional."""
        raise NotImplementedError(f"{self.name} does not support index data")

    def get_money_flow(self, symbol: str) -> pd.DataFrame:
        """Get capital/money flow data. Optional."""
        raise NotImplementedError(f"{self.name} does not support money flow data")

    def search(self, keyword: str) -> list[StockInfo]:
        """Search for stocks by keyword. Optional."""
        raise NotImplementedError(f"{self.name} does not support search")

    def is_available(self) -> bool:
        """Check if the adapter is available and configured."""
        return True

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} markets={self.supported_markets}>"
