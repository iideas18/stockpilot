"""AKShare data adapter — primary data source for A-share (Chinese) market.

Wraps the akshare library to conform to the BaseDataAdapter interface.
AKShare provides 200+ free APIs for Chinese financial markets.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import pandas as pd

from stockpilot.data.adapters import BaseDataAdapter, Market, StockInfo, TimeFrame

logger = logging.getLogger(__name__)


class AKShareAdapter(BaseDataAdapter):
    """AKShare adapter for A-share market data."""

    name = "akshare"
    supported_markets = [Market.A_SHARE]

    def __init__(self) -> None:
        try:
            import akshare as ak
            self._ak = ak
        except ImportError:
            raise ImportError("akshare is required: pip install akshare")

    def get_stock_list(self, market: Market = Market.A_SHARE) -> pd.DataFrame:
        """Get all A-share stock listings."""
        try:
            df = self._ak.stock_info_a_code_name()
            df.columns = ["symbol", "name"]
            return df
        except Exception as e:
            logger.warning("Failed to fetch stock list: %s", e)
            return pd.DataFrame(columns=["symbol", "name"])

    def get_price_history(
        self,
        symbol: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        timeframe: TimeFrame = TimeFrame.DAILY,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """Get historical OHLCV data via ak.stock_zh_a_hist."""
        start = self._to_date_str(start_date) if start_date else "19700101"
        end = self._to_date_str(end_date) if end_date else self._to_date_str(date.today())

        period_map = {
            TimeFrame.DAILY: "daily",
            TimeFrame.WEEKLY: "weekly",
            TimeFrame.MONTHLY: "monthly",
        }
        period = period_map.get(timeframe, "daily")

        df = self._ak.stock_zh_a_hist(
            symbol=symbol,
            period=period,
            start_date=start,
            end_date=end,
            adjust=adjust,
        )
        return self._normalize_price_df(df)

    def get_realtime_quote(self, symbol: str) -> dict[str, Any]:
        """Get real-time quote for a single stock."""
        df = self.get_realtime_quotes([symbol])
        if df.empty:
            return {}
        return df.iloc[0].to_dict()

    def get_realtime_quotes(self, symbols: list[str]) -> pd.DataFrame:
        """Get real-time quotes for multiple A-share stocks."""
        df = self._ak.stock_zh_a_spot_em()
        # Filter to requested symbols
        df = df[df["代码"].isin(symbols)]
        return self._normalize_realtime_df(df)

    def get_fundamental_data(self, symbol: str) -> dict[str, Any]:
        """Get PE, PB, market cap etc. from real-time spot data."""
        df = self._ak.stock_zh_a_spot_em()
        row = df[df["代码"] == symbol]
        if row.empty:
            return {}
        row = row.iloc[0]
        return {
            "symbol": symbol,
            "pe_ratio": row.get("市盈率-动态"),
            "pb_ratio": row.get("市净率"),
            "total_market_cap": row.get("总市值"),
            "circulating_market_cap": row.get("流通市值"),
            "turnover_rate": row.get("换手率"),
            "volume_ratio": row.get("量比"),
        }

    def get_financial_statements(
        self,
        symbol: str,
        report_type: str = "income",
        period: str = "annual",
    ) -> pd.DataFrame:
        """Get financial statements from AKShare."""
        func_map = {
            "income": self._ak.stock_profit_sheet_by_report_em,
            "balance": self._ak.stock_balance_sheet_by_report_em,
            "cashflow": self._ak.stock_cash_flow_sheet_by_report_em,
        }
        func = func_map.get(report_type)
        if func is None:
            raise ValueError(f"Unknown report_type: {report_type}")
        return func(symbol=symbol)

    def get_dividend_history(self, symbol: str) -> pd.DataFrame:
        """Get historical dividends."""
        return self._ak.stock_history_dividend_detail(symbol=symbol, indicator="分红")

    def get_industry_data(self, market: Market = Market.A_SHARE) -> pd.DataFrame:
        """Get industry classification."""
        return self._ak.stock_board_industry_name_em()

    def get_index_data(
        self,
        symbol: str,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
    ) -> pd.DataFrame:
        """Get index historical data (e.g., '000001' for 上证指数)."""
        start = self._to_date_str(start_date) if start_date else "19700101"
        end = self._to_date_str(end_date) if end_date else self._to_date_str(date.today())
        df = self._ak.stock_zh_index_daily(symbol=f"sh{symbol}")
        if not df.empty:
            df = df[(df["date"] >= start) & (df["date"] <= end)]
        return df

    def get_money_flow(self, symbol: str) -> pd.DataFrame:
        """Get individual stock money flow data."""
        return self._ak.stock_individual_fund_flow(stock=symbol, market="sh")

    def search(self, keyword: str) -> list[StockInfo]:
        """Search stocks by name or code."""
        df = self.get_stock_list()
        mask = df["symbol"].str.contains(keyword) | df["name"].str.contains(keyword, na=False)
        results = df[mask].head(20)
        return [
            StockInfo(symbol=row["symbol"], name=row["name"], market=Market.A_SHARE)
            for _, row in results.iterrows()
        ]

    # ── helpers ──

    @staticmethod
    def _to_date_str(d: str | date | datetime) -> str:
        if isinstance(d, str):
            return d.replace("-", "")
        return d.strftime("%Y%m%d")

    @staticmethod
    def _normalize_price_df(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize AKShare price columns to standard names."""
        col_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "change_pct",
            "涨跌额": "change",
            "换手率": "turnover_rate",
        }
        df = df.rename(columns=col_map)
        return df

    @staticmethod
    def _normalize_realtime_df(df: pd.DataFrame) -> pd.DataFrame:
        """Normalize real-time quote columns."""
        col_map = {
            "代码": "symbol",
            "名称": "name",
            "最新价": "price",
            "涨跌额": "change",
            "涨跌幅": "change_pct",
            "成交量": "volume",
            "成交额": "amount",
            "今开": "open",
            "最高": "high",
            "最低": "low",
            "昨收": "prev_close",
        }
        return df.rename(columns=col_map)
