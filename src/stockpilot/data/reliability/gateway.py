"""DataGateway: high-level request builder over the ReliabilityShield.

Callers (API routes, CLI, agent tools) interact with this gateway rather than
with adapters directly. Each public method:

1. Builds a typed ``DomainRequest``.
2. Defines a ``fetch_live(adapter, request)`` closure that calls the right
   adapter method.
3. Delegates orchestration to ``ReliabilityShield.execute``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from stockpilot.data.adapters import Market
from stockpilot.data.reliability.shield import ReliabilityShield
from stockpilot.data.reliability.types import (
    CacheClass,
    DataResult,
    DomainId,
    DomainRequest,
    ReliabilityError,
    ResultKind,
)


def _coerce_market(market: Market | str) -> str:
    if isinstance(market, Market):
        return market.value
    return str(market)


def _coerce_market_enum(market: Market | str) -> Market:
    if isinstance(market, Market):
        return market
    try:
        return Market(str(market))
    except ValueError:
        return Market.A_SHARE


def _coerce_date(value: date | str | None) -> date | None:
    if value is None or isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


class DataGateway:
    """Facade over the reliability shield with per-domain helpers."""

    def __init__(self, shield: ReliabilityShield) -> None:
        self.shield = shield

    # ---------------------------------------------------------- request build

    def build_price_history_request(
        self,
        symbol: str,
        market: Market | str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        timeframe: str | None = None,
        adjust: str = "qfq",
        adapter_name: str = "auto",
        now_override: str | None = None,
    ) -> DomainRequest:
        market_key = _coerce_market(market)
        start = _coerce_date(start_date)
        end = _coerce_date(end_date)
        cache_class = self.shield.classify_cache_class(
            DomainId.PRICE_HISTORY,
            market_key,
            start,
            end,
            now_override=now_override,
        )
        return DomainRequest(
            domain=DomainId.PRICE_HISTORY,
            market=market_key,
            symbol=symbol,
            start_date=start,
            end_date=end,
            timeframe=timeframe,
            adjust=adjust,
            cache_class=cache_class,
            adapter_name=adapter_name or "auto",
        )

    # -------------------------------------------------------------- methods

    def get_price_history(
        self,
        symbol: str,
        market: Market | str,
        start_date: date | str | None = None,
        end_date: date | str | None = None,
        timeframe: str | None = None,
        adjust: str = "qfq",
        adapter_name: str = "auto",
        now_override: str | None = None,
    ) -> DataResult:
        request = self.build_price_history_request(
            symbol,
            market,
            start_date=start_date,
            end_date=end_date,
            timeframe=timeframe,
            adjust=adjust,
            adapter_name=adapter_name,
            now_override=now_override,
        )

        def fetch_live(adapter, req: DomainRequest):
            return adapter.get_price_history(
                req.symbol,
                start_date=req.start_date,
                end_date=req.end_date,
                adjust=req.adjust,
            )

        return self.shield.execute(request, fetch_live)

    def get_realtime_quote(
        self,
        symbol: str,
        market: Market | str,
        adapter_name: str = "auto",
    ) -> DataResult:
        request = DomainRequest(
            domain=DomainId.REALTIME_QUOTE,
            market=_coerce_market(market),
            symbol=symbol,
            cache_class=CacheClass.LIVE_QUOTE,
            adapter_name=adapter_name or "auto",
        )

        def fetch_live(adapter, req: DomainRequest):
            return adapter.get_realtime_quote(req.symbol)

        return self.shield.execute(request, fetch_live)

    def get_realtime_quotes(
        self,
        symbols: list[str],
        market: Market | str,
        require_complete: bool = False,
        adapter_name: str = "auto",
    ) -> DataResult:
        symbols_tuple = tuple(symbols or ())
        request = DomainRequest(
            domain=DomainId.REALTIME_QUOTES,
            market=_coerce_market(market),
            symbols=symbols_tuple,
            cache_class=CacheClass.LIVE_QUOTE,
            adapter_name=adapter_name or "auto",
            require_complete=require_complete,
        )

        def fetch_live(adapter, req: DomainRequest):
            return adapter.get_realtime_quotes(list(req.symbols))

        result = self.shield.execute(request, fetch_live)

        # Aggregate: handle partial batches according to require_complete.
        if result.error is not None or result.data is None:
            return result

        df = result.data
        if not isinstance(df, pd.DataFrame):
            return result

        returned_symbols = set()
        if "symbol" in df.columns:
            returned_symbols = set(str(s) for s in df["symbol"].tolist())
        missing = tuple(s for s in symbols_tuple if s not in returned_symbols)

        if not missing:
            return result

        if require_complete:
            err = ReliabilityError(
                status="unavailable",
                code="DATASET_INCOMPLETE",
                message=(
                    f"{len(missing)} of {len(symbols_tuple)} symbols missing "
                    f"from quote batch"
                ),
                domain=DomainId.REALTIME_QUOTES.value,
                market=_coerce_market(market),
                missing_symbols=missing,
                attempted_sources=result.attempted_sources,
                http_status=503,
            )
            return DataResult(
                status="unavailable",
                result_kind=ResultKind.PARTIAL,
                cache_key=result.cache_key,
                source=result.source,
                served_from_cache=result.served_from_cache,
                fetched_at=result.fetched_at,
                age_seconds=result.age_seconds,
                degraded_reason=None,
                missing_symbols=missing,
                attempted_sources=result.attempted_sources,
                error=err,
            )

        result.result_kind = ResultKind.PARTIAL
        result.missing_symbols = missing
        result.degraded_reason = "quote provider returned partial batch"
        return result

    def get_fundamental_data(
        self,
        symbol: str,
        market: Market | str,
        adapter_name: str = "auto",
    ) -> DataResult:
        request = DomainRequest(
            domain=DomainId.FUNDAMENTAL_DATA,
            market=_coerce_market(market),
            symbol=symbol,
            cache_class=CacheClass.REFERENCE_DATA,
            adapter_name=adapter_name or "auto",
        )

        def fetch_live(adapter, req: DomainRequest):
            return adapter.get_fundamental_data(req.symbol)

        return self.shield.execute(request, fetch_live)

    def get_stock_list(
        self,
        market: Market | str,
        adapter_name: str = "auto",
    ) -> DataResult:
        market_key = _coerce_market(market)
        market_enum = _coerce_market_enum(market)
        request = DomainRequest(
            domain=DomainId.STOCK_LIST,
            market=market_key,
            cache_class=CacheClass.REFERENCE_DATA,
            adapter_name=adapter_name or "auto",
        )

        def fetch_live(adapter, req: DomainRequest):
            return adapter.get_stock_list(market_enum)

        return self.shield.execute(request, fetch_live)

    def search(
        self,
        keyword: str,
        market: Market | str,
        adapter_name: str = "auto",
    ) -> DataResult:
        request = DomainRequest(
            domain=DomainId.SEARCH,
            market=_coerce_market(market),
            keyword=keyword,
            cache_class=CacheClass.REFERENCE_DATA,
            adapter_name=adapter_name or "auto",
        )

        def fetch_live(adapter, req: DomainRequest):
            return adapter.search(req.keyword)

        return self.shield.execute(request, fetch_live)
