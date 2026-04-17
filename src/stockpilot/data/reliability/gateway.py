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


_ERROR_PRECEDENCE = {"invalid_request": 0, "not_found": 1, "unavailable": 2}


def _tagged_sources(symbol: str, entries: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    tagged: list[dict[str, Any]] = []
    for entry in entries:
        item = dict(entry)
        item.setdefault("symbol", symbol)
        tagged.append(item)
    return tagged


def aggregate_route_status(
    per_symbol_pairs: list[tuple[str, DataResult]],
) -> DataResult:
    """Aggregate per-symbol ``DataResult`` values into one route-level envelope.

    Rules (spec lines 1539-1566):
    - If any input is ``result_kind=partial`` => DATASET_INCOMPLETE (503)
    - If any input has an error, pick by precedence: invalid_request > not_found > unavailable
    - Otherwise fold success metadata across inputs with deterministic rules.
    - ``attempted_sources`` is flattened with caller-supplied symbol injected.
    """
    attempted: list[dict[str, Any]] = []
    for symbol, result in per_symbol_pairs:
        attempted.extend(_tagged_sources(symbol, result.attempted_sources))

    # Step 1: partial results short-circuit to DATASET_INCOMPLETE.
    for symbol, result in per_symbol_pairs:
        if result.result_kind == ResultKind.PARTIAL:
            missing = tuple(result.missing_symbols)
            err = ReliabilityError(
                status="dataset_incomplete",
                code="DATASET_INCOMPLETE",
                message=f"Required dataset incomplete: missing {list(missing)}",
                domain=(result.error.domain if result.error else "price_history"),
                market=(result.error.market if result.error else ""),
                symbol=symbol,
                missing_symbols=missing,
                attempted_sources=tuple(attempted),
                http_status=503,
            )
            return DataResult(
                status="dataset_incomplete",
                result_kind=ResultKind.PARTIAL,
                cache_key="",
                source="mixed",
                served_from_cache=False,
                fetched_at=None,
                age_seconds=None,
                degraded_reason=None,
                missing_symbols=missing,
                attempted_sources=tuple(attempted),
                data=None,
                error=err,
            )

    # Step 2: errors (deterministic precedence).
    errored = [
        (symbol, result)
        for symbol, result in per_symbol_pairs
        if result.error is not None
    ]
    if errored:
        errored.sort(key=lambda p: _ERROR_PRECEDENCE.get(p[1].error.status, 99))
        symbol, result = errored[0]
        err = result.error
        # Rebuild the error so attempted_sources is flattened and symbol-tagged.
        merged_err = ReliabilityError(
            status=err.status,
            code=err.code,
            message=err.message,
            domain=err.domain,
            market=err.market,
            symbol=err.symbol or symbol,
            missing_symbols=err.missing_symbols,
            attempted_sources=tuple(attempted),
            cache_state=err.cache_state,
            retry_after_seconds=err.retry_after_seconds,
            http_status=err.http_status,
        )
        return DataResult(
            status=err.status,
            result_kind=ResultKind.EMPTY,
            cache_key="",
            source="none",
            served_from_cache=False,
            fetched_at=None,
            age_seconds=None,
            degraded_reason=None,
            missing_symbols=err.missing_symbols,
            attempted_sources=tuple(attempted),
            data=None,
            error=merged_err,
        )

    # Step 3: success aggregation.
    served_from_cache = any(
        result.served_from_cache for _, result in per_symbol_pairs
    )
    fetched_ats = [result.fetched_at for _, result in per_symbol_pairs if result.fetched_at is not None]
    oldest_fetched_at = min(fetched_ats) if fetched_ats else None
    ages = [result.age_seconds for _, result in per_symbol_pairs if result.age_seconds is not None]
    max_age = max(ages) if ages else None

    any_stale = any(result.status == "stale" for _, result in per_symbol_pairs)
    agg_status = "stale" if any_stale else "fresh"

    degraded_reason = None
    if agg_status == "stale":
        for _, result in per_symbol_pairs:
            if result.degraded_reason:
                degraded_reason = result.degraded_reason
                break

    sources = {result.source for _, result in per_symbol_pairs}
    if len(sources) == 1:
        source = next(iter(sources))
    else:
        source = "mixed"

    return DataResult(
        status=agg_status,
        result_kind=ResultKind.DATA,
        cache_key="",
        source=source,
        served_from_cache=served_from_cache,
        fetched_at=oldest_fetched_at,
        age_seconds=max_age,
        degraded_reason=degraded_reason,
        missing_symbols=(),
        attempted_sources=tuple(attempted),
        data=None,
        error=None,
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
