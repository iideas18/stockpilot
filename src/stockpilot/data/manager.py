"""DataManager — central routing layer for all data access.

Routes requests to the appropriate adapter based on market and configuration.
Handles caching transparently.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import pandas as pd

from stockpilot.data.adapters import BaseDataAdapter, Market, StockInfo, TimeFrame
from stockpilot.data.cache import CacheBackend, DataCache, MemoryCache, RedisCache

logger = logging.getLogger(__name__)


def _cache_market_key(market: Market | None) -> str:
    return market.value if isinstance(market, Market) else str(market or "default")


class DataManager:
    """Unified data access layer that routes to adapters and caches results.

    Usage:
        dm = DataManager()
        dm.register_adapter(AKShareAdapter())
        dm.register_adapter(YFinanceAdapter())
        df = dm.get_price_history("000001", market=Market.A_SHARE)
        df = dm.get_price_history("AAPL", market=Market.US)
    """

    def __init__(
        self,
        cache_backend: CacheBackend | None = None,
        default_ttl: int = 3600,
        price_ttl: int = 300,
    ) -> None:
        self._adapters: dict[str, BaseDataAdapter] = {}
        self._market_routing: dict[Market, str] = {}

        backend = cache_backend or MemoryCache()
        self._cache = DataCache(backend, default_ttl)
        self._price_ttl = price_ttl

    def register_adapter(self, adapter: BaseDataAdapter, priority: bool = False) -> None:
        """Register a data adapter. If priority=True, it becomes the default for its markets."""
        self._adapters[adapter.name] = adapter
        for market in adapter.supported_markets:
            if priority or market not in self._market_routing:
                self._market_routing[market] = adapter.name
        logger.info("Registered adapter: %s (markets: %s)", adapter.name, adapter.supported_markets)

    def get_adapter(self, name: str | None = None, market: Market | None = None) -> BaseDataAdapter:
        """Get adapter by name or by market routing."""
        if name and name in self._adapters:
            return self._adapters[name]
        if market and market in self._market_routing:
            return self._adapters[self._market_routing[market]]
        if self._adapters:
            return next(iter(self._adapters.values()))
        raise RuntimeError("No data adapters registered")

    def _get_price_history_adapters(
        self,
        *,
        adapter_name: str | None = None,
        market: Market | None = None,
    ) -> list[BaseDataAdapter]:
        """Return candidate adapters in failover order for price history."""
        if adapter_name:
            return [self.get_adapter(name=adapter_name)]

        candidates: list[BaseDataAdapter] = []
        seen: set[str] = set()

        def add_candidate(adapter: BaseDataAdapter) -> None:
            if adapter.name not in seen:
                candidates.append(adapter)
                seen.add(adapter.name)

        routed_name = self._market_routing.get(market) if market is not None else None
        if routed_name and routed_name in self._adapters:
            add_candidate(self._adapters[routed_name])

        if market is not None:
            for adapter in self._adapters.values():
                if market in adapter.supported_markets:
                    add_candidate(adapter)
        else:
            for adapter in self._adapters.values():
                add_candidate(adapter)

        if not candidates and self._adapters:
            add_candidate(next(iter(self._adapters.values())))

        if not candidates:
            raise RuntimeError("No data adapters registered")

        return candidates

    def get_price_history(
        self,
        symbol: str,
        market: Market | None = None,
        start_date: str | date | None = None,
        end_date: str | date | None = None,
        timeframe: TimeFrame = TimeFrame.DAILY,
        adjust: str = "qfq",
        adapter_name: str | None = None,
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """Get historical OHLCV data with caching."""
        cache_key = self._cache.make_key(
            "price",
            symbol=symbol,
            market=_cache_market_key(market),
            adapter=adapter_name or "auto",
            start=str(start_date),
            end=str(end_date),
            tf=timeframe.value,
            adjust=adjust,
        )
        if use_cache:
            cached = self._cache.get_dataframe(cache_key)
            if cached is not None:
                logger.debug("Cache hit: price history for %s", symbol)
                return cached

        last_error: Exception | None = None
        empty_result: pd.DataFrame | None = None
        for adapter in self._get_price_history_adapters(adapter_name=adapter_name, market=market):
            try:
                df = adapter.get_price_history(symbol, start_date, end_date, timeframe, adjust)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Price history adapter %s failed for %s (%s): %s",
                    adapter.name,
                    symbol,
                    market,
                    exc,
                )
                continue

            if df.empty:
                empty_result = df
                logger.info(
                    "Price history adapter %s returned no data for %s (%s)",
                    adapter.name,
                    symbol,
                    market,
                )
                continue

            if use_cache:
                self._cache.set_dataframe(cache_key, df)

            return df

        if last_error is not None:
            raise last_error

        return empty_result if empty_result is not None else pd.DataFrame()

    def get_realtime_quote(
        self,
        symbol: str,
        market: Market | None = None,
        adapter_name: str | None = None,
    ) -> dict[str, Any]:
        """Get real-time quote with short-TTL cache."""
        cache_key = self._cache.make_key("quote", symbol=symbol)
        cached = self._cache.get_dict(cache_key)
        if cached is not None:
            return cached

        adapter = self.get_adapter(name=adapter_name, market=market)
        result = adapter.get_realtime_quote(symbol)

        if result:
            self._cache.set_dict(cache_key, result, ttl=self._price_ttl)

        return result

    def get_realtime_quotes(
        self,
        symbols: list[str],
        market: Market | None = None,
        adapter_name: str | None = None,
    ) -> pd.DataFrame:
        """Get real-time quotes for multiple symbols."""
        adapter = self.get_adapter(name=adapter_name, market=market)
        return adapter.get_realtime_quotes(symbols)

    def get_fundamental_data(
        self,
        symbol: str,
        market: Market | None = None,
        adapter_name: str | None = None,
    ) -> dict[str, Any]:
        """Get fundamental data with caching."""
        cache_key = self._cache.make_key(
            "fundamental",
            symbol=symbol,
            market=_cache_market_key(market),
            adapter=adapter_name or "auto",
        )
        cached = self._cache.get_dict(cache_key)
        if cached is not None:
            return cached

        adapter = self.get_adapter(name=adapter_name, market=market)
        result = adapter.get_fundamental_data(symbol)

        if result:
            self._cache.set_dict(cache_key, result)

        return result

    def get_financial_statements(
        self,
        symbol: str,
        report_type: str = "income",
        period: str = "annual",
        market: Market | None = None,
        adapter_name: str | None = None,
    ) -> pd.DataFrame:
        """Get financial statements."""
        adapter = self.get_adapter(name=adapter_name, market=market)
        return adapter.get_financial_statements(symbol, report_type, period)

    def get_stock_list(
        self,
        market: Market = Market.A_SHARE,
        adapter_name: str | None = None,
    ) -> pd.DataFrame:
        """Get stock list for a market."""
        cache_key = self._cache.make_key("stock_list", market=market.value)
        cached = self._cache.get_dataframe(cache_key)
        if cached is not None:
            return cached

        adapter = self.get_adapter(name=adapter_name, market=market)
        df = adapter.get_stock_list(market)

        if not df.empty:
            self._cache.set_dataframe(cache_key, df, ttl=86400)  # 24h cache

        return df

    def search(
        self,
        keyword: str,
        market: Market | None = None,
    ) -> list[StockInfo]:
        """Search for stocks across adapters."""
        results: list[StockInfo] = []
        adapters = (
            [self.get_adapter(market=market)]
            if market
            else list(self._adapters.values())
        )
        for adapter in adapters:
            try:
                results.extend(adapter.search(keyword))
            except NotImplementedError:
                continue
        return results

    @property
    def available_adapters(self) -> list[str]:
        return list(self._adapters.keys())

    @property
    def market_routing(self) -> dict[Market, str]:
        return dict(self._market_routing)
