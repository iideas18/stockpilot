"""Shared fake gateways for API/CLI contract tests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

from stockpilot.data.reliability.types import (
    DataResult,
    ReliabilityError,
    ResultKind,
)


DEFAULT_FETCHED_AT = "2026-04-17T09:25:00Z"
DEFAULT_STALE_AGE_SECONDS = 600
DEFAULT_STALE_REASON = "live sources unavailable; serving cached payload"
DEFAULT_RETRY_AFTER_SECONDS = 120


class _ZuluDatetime(datetime):
    """``datetime`` subclass whose ``isoformat()`` emits a ``Z`` suffix.

    The reliability envelope contract (spec lines 953, 1390) requires
    ``fetched_at`` to be serialized as e.g. ``"2026-04-17T09:25:00Z"`` rather
    than the stdlib default ``"+00:00"`` offset form. Tests rely on exact
    string equality, so we return a real ``datetime`` instance that round-trips
    through ``DataResult.to_status_dict()`` while preserving the Z form.
    """

    def isoformat(self, sep: str = "T", timespec: str = "auto") -> str:  # type: ignore[override]
        base = super().isoformat(sep=sep, timespec=timespec)
        if base.endswith("+00:00"):
            return base[:-6] + "Z"
        return base


def _parse_fetched_at(value: str) -> _ZuluDatetime:
    normalized = value.replace("Z", "+00:00") if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    return _ZuluDatetime(
        parsed.year,
        parsed.month,
        parsed.day,
        parsed.hour,
        parsed.minute,
        parsed.second,
        parsed.microsecond,
        tzinfo=parsed.tzinfo,
    )


def sample_price_history(symbol: str) -> pd.DataFrame:
    dates = pd.date_range("2026-02-01", periods=60, freq="D")
    return pd.DataFrame(
        {
            "date": dates,
            "open": [100 + i for i in range(60)],
            "high": [101 + i for i in range(60)],
            "low": [99 + i for i in range(60)],
            "close": [100.5 + i for i in range(60)],
            "volume": [1_000_000 + i * 1000 for i in range(60)],
            "symbol": [symbol] * 60,
        }
    )


def sample_fundamental_data(symbol: str) -> dict:
    return {
        "symbol": symbol,
        "company_name": f"{symbol} Inc.",
        "market_cap": 1_000_000_000,
        "pe_ratio": 18.5,
        "pb_ratio": 2.1,
    }


def _build_payload(domain: str, symbol: str, result_kind: str) -> Any:
    if result_kind == "empty":
        if domain == "price_history":
            return pd.DataFrame()
        return None
    if domain == "price_history":
        return sample_price_history(symbol)
    if domain == "fundamental_data":
        return sample_fundamental_data(symbol)
    return None


def build_result(
    *,
    domain: str,
    status: str,
    result_kind: str,
    source: str,
    served_from_cache: bool = False,
    age_seconds: int | None = None,
    fetched_at: str | None = None,
    degraded_reason: str | None = None,
    missing_symbols: list[str] | None = None,
    attempted_sources: list[dict[str, Any]] | None = None,
    symbol: str = "AAPL",
) -> DataResult:
    if fetched_at is None:
        fetched_at = DEFAULT_FETCHED_AT
    if degraded_reason is None and status == "stale":
        degraded_reason = DEFAULT_STALE_REASON
    if age_seconds is None and status == "stale":
        age_seconds = DEFAULT_STALE_AGE_SECONDS
    if missing_symbols is None:
        missing_symbols = []
    if attempted_sources is None:
        attempted_sources = []

    kind_enum = ResultKind(result_kind)
    data = _build_payload(domain, symbol, result_kind)

    return DataResult(
        status=status,
        result_kind=kind_enum,
        cache_key=f"{domain}:{symbol}",
        source=source,
        served_from_cache=served_from_cache,
        fetched_at=_parse_fetched_at(fetched_at),
        age_seconds=age_seconds,
        degraded_reason=degraded_reason,
        missing_symbols=tuple(missing_symbols),
        attempted_sources=tuple(attempted_sources),
        data=data,
        error=None,
    )


def build_error_result(
    *,
    domain: str,
    status: str,
    code: str,
    http_status: int,
    symbol: str = "AAPL",
    market: str = "us",
    message: str | None = None,
    retry_after_seconds: int | None = None,
    missing_symbols: list[str] | None = None,
    attempted_sources: list[dict[str, Any]] | None = None,
) -> DataResult:
    if message is None:
        message = f"{code} for {domain}"
    if retry_after_seconds is None and http_status == 503:
        retry_after_seconds = DEFAULT_RETRY_AFTER_SECONDS
    if missing_symbols is None:
        missing_symbols = []
    if attempted_sources is None:
        attempted_sources = []

    err = ReliabilityError(
        status=status,
        code=code,
        message=message,
        domain=domain,
        market=market,
        symbol=symbol,
        missing_symbols=tuple(missing_symbols),
        attempted_sources=tuple(attempted_sources),
        retry_after_seconds=retry_after_seconds,
        http_status=http_status,
    )

    return DataResult(
        status=status,
        result_kind=ResultKind.EMPTY,
        cache_key=f"{domain}:{symbol}",
        source="none",
        served_from_cache=False,
        fetched_at=None,
        age_seconds=None,
        degraded_reason=None,
        missing_symbols=tuple(missing_symbols),
        attempted_sources=tuple(attempted_sources),
        data=None,
        error=err,
    )


class FakeGateway:
    """Tiny gateway fake used only by API/CLI contract tests."""

    def __init__(
        self,
        *,
        single_result: DataResult | None = None,
        per_symbol: dict[str, DataResult] | None = None,
    ) -> None:
        self.single_result = single_result
        self.per_symbol = per_symbol or {}

    @classmethod
    def single(
        cls,
        *,
        domain: str,
        status: str,
        result_kind: str,
        source: str,
        served_from_cache: bool = False,
        age_seconds: int | None = None,
    ) -> "FakeGateway":
        outcome = (
            "error" if status == "stale"
            else ("empty" if result_kind == "empty" else "success")
        )
        return cls(
            single_result=build_result(
                domain=domain,
                status=status,
                result_kind=result_kind,
                source=source,
                served_from_cache=served_from_cache,
                age_seconds=age_seconds,
                attempted_sources=[
                    {
                        "adapter": source.split(":")[-1],
                        "outcome": outcome,
                    }
                ],
            )
        )

    @classmethod
    def error(
        cls,
        *,
        domain: str,
        status: str,
        code: str,
        http_status: int,
    ) -> "FakeGateway":
        return cls(
            single_result=build_error_result(
                domain=domain,
                status=status,
                code=code,
                http_status=http_status,
            )
        )

    @classmethod
    def multi(
        cls,
        *,
        status: str | None = None,
        source: str | None = None,
        result_kind: str = "data",
        served_from_cache: bool = False,
        empty_symbols: list[str] | None = None,
        unavailable_symbols: list[str] | None = None,
    ) -> "FakeGateway":
        empty = set(empty_symbols or [])
        unavailable = set(unavailable_symbols or [])
        per_symbol: dict[str, DataResult] = {}
        for symbol in ("AAA", "BBB"):
            if symbol in unavailable:
                per_symbol[symbol] = build_error_result(
                    domain="price_history",
                    status="unavailable",
                    code="DATA_SOURCE_UNAVAILABLE",
                    http_status=503,
                    symbol=symbol,
                    market="us",
                )
                continue
            per_symbol[symbol] = build_result(
                domain="price_history",
                status=status or "fresh",
                result_kind="empty" if symbol in empty else result_kind,
                source=source or "akshare",
                served_from_cache=served_from_cache,
                symbol=symbol,
                attempted_sources=[
                    {
                        "symbol": symbol,
                        "adapter": "akshare",
                        "outcome": "empty" if symbol in empty else "success",
                    }
                ],
            )
        return cls(per_symbol=per_symbol)

    def get_price_history(self, symbol: str, **kwargs: Any) -> DataResult:
        return self.per_symbol.get(symbol, self.single_result)

    def get_fundamental_data(self, symbol: str, **kwargs: Any) -> DataResult:
        return self.single_result

    def get_realtime_quotes(self, symbols: list[str], market: str = "us", **kwargs: Any) -> DataResult:
        return self.single_result


class RecordingGateway:
    """Returns one canned result for any symbol and records request args."""

    def __init__(self, result: DataResult) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    def get_price_history(self, symbol: str, **kwargs: Any) -> DataResult:
        self.calls.append({"symbol": symbol, **kwargs})
        return self.result

    def get_fundamental_data(self, symbol: str, **kwargs: Any) -> DataResult:
        self.calls.append({"symbol": symbol, **kwargs})
        return self.result


# --- Prebuilt gateway constructors ------------------------------------------


def gateway_with_stale_single_result(*, domain: str, source: str) -> FakeGateway:
    return FakeGateway.single(
        domain=domain,
        status="stale",
        result_kind="data",
        source=source,
        served_from_cache=True,
        age_seconds=DEFAULT_STALE_AGE_SECONDS,
    )


def gateway_with_empty_result(*, domain: str) -> FakeGateway:
    return FakeGateway.single(
        domain=domain,
        status="fresh",
        result_kind="empty",
        source="yfinance",
    )


def gateway_with_invalid_request(*, domain: str) -> FakeGateway:
    return FakeGateway.error(
        domain=domain,
        status="invalid_request",
        code="DATA_REQUEST_INVALID",
        http_status=400,
    )


def gateway_with_invalid_required_symbol() -> FakeGateway:
    return FakeGateway(
        per_symbol={
            "AAA": build_result(
                domain="price_history",
                status="fresh",
                result_kind="data",
                source="yfinance",
                symbol="AAA",
                attempted_sources=[{"adapter": "yfinance", "outcome": "success"}],
            ),
            "BBB": build_error_result(
                domain="price_history",
                status="invalid_request",
                code="DATA_REQUEST_INVALID",
                http_status=400,
                symbol="BBB",
                market="us",
            ),
        }
    )


def gateway_with_partial_required_symbol() -> FakeGateway:
    return FakeGateway(
        per_symbol={
            "AAA": build_result(
                domain="price_history",
                status="fresh",
                result_kind="partial",
                source="yfinance",
                symbol="AAA",
                missing_symbols=["BBB"],
                attempted_sources=[{"adapter": "yfinance", "outcome": "partial"}],
            ),
            "BBB": build_result(
                domain="price_history",
                status="fresh",
                result_kind="data",
                source="yfinance",
                symbol="BBB",
                attempted_sources=[{"adapter": "yfinance", "outcome": "success"}],
            ),
        }
    )


def gateway_with_unavailable_required_symbol() -> FakeGateway:
    return FakeGateway.multi(
        status="fresh", source="yfinance", unavailable_symbols=["BBB"]
    )


def gateway_with_unavailable_single_result(*, domain: str) -> FakeGateway:
    return FakeGateway.error(
        domain=domain,
        status="unavailable",
        code="DATA_SOURCE_UNAVAILABLE",
        http_status=503,
    )


def gateway_with_empty_required_symbol() -> FakeGateway:
    return FakeGateway.multi(
        status="fresh", source="yfinance", empty_symbols=["BBB"]
    )


def gateway_with_compare_results() -> FakeGateway:
    return FakeGateway(
        per_symbol={
            "AAA": build_result(
                domain="price_history",
                status="fresh",
                result_kind="data",
                source="yfinance",
                served_from_cache=False,
                age_seconds=0,
                fetched_at="2026-04-17T09:35:00Z",
                symbol="AAA",
                attempted_sources=[{"adapter": "yfinance", "outcome": "success"}],
            ),
            "BBB": build_result(
                domain="price_history",
                status="stale",
                result_kind="data",
                source="cache:akshare",
                served_from_cache=True,
                age_seconds=DEFAULT_STALE_AGE_SECONDS,
                fetched_at="2026-04-17T09:25:00Z",
                degraded_reason=DEFAULT_STALE_REASON,
                symbol="BBB",
                attempted_sources=[
                    {
                        "adapter": "akshare",
                        "outcome": "error",
                        "reason": "ConnectionError",
                    }
                ],
            ),
        }
    )


# --- aggregate_route_status DataResult builders ------------------------------


def _direct_result(
    *,
    status: str,
    result_kind: ResultKind,
    source: str,
    served_from_cache: bool = False,
    fetched_at: datetime | None = None,
    age_seconds: int | None = None,
    degraded_reason: str | None = None,
    missing_symbols: tuple[str, ...] = (),
    attempted_sources: tuple[dict, ...] = (),
    error: ReliabilityError | None = None,
    data: Any = None,
) -> DataResult:
    return DataResult(
        status=status,
        result_kind=result_kind,
        cache_key="k",
        source=source,
        served_from_cache=served_from_cache,
        fetched_at=fetched_at,
        age_seconds=age_seconds,
        degraded_reason=degraded_reason,
        missing_symbols=missing_symbols,
        attempted_sources=attempted_sources,
        data=data,
        error=error,
    )


def fresh_result(*, source: str = "yfinance") -> DataResult:
    return _direct_result(
        status="fresh",
        result_kind=ResultKind.DATA,
        source=source,
        served_from_cache=False,
        fetched_at=datetime(2026, 4, 17, 9, 35, tzinfo=timezone.utc),
        age_seconds=0,
        data={"ok": True},
        attempted_sources=({"adapter": source, "outcome": "success"},),
    )


def stale_result(*, source: str = "cache:akshare", age_seconds: int = 600) -> DataResult:
    return _direct_result(
        status="stale",
        result_kind=ResultKind.DATA,
        source=source,
        served_from_cache=True,
        fetched_at=datetime(2026, 4, 17, 9, 25, tzinfo=timezone.utc),
        age_seconds=age_seconds,
        degraded_reason="live sources unavailable; serving cached payload",
        data={"ok": True},
        attempted_sources=({"adapter": source.split(":")[-1], "outcome": "error"},),
    )


def invalid_request_result() -> DataResult:
    err = ReliabilityError(
        status="invalid_request",
        code="DATA_REQUEST_INVALID",
        message="bad",
        domain="price_history",
        market="us",
        http_status=400,
    )
    return _direct_result(
        status="invalid_request", result_kind=ResultKind.EMPTY, source="none", error=err
    )


def empty_result() -> DataResult:
    err = ReliabilityError(
        status="not_found",
        code="DATA_NOT_FOUND",
        message="missing",
        domain="price_history",
        market="us",
        http_status=404,
    )
    return _direct_result(
        status="not_found", result_kind=ResultKind.EMPTY, source="none", error=err
    )


def unavailable_result() -> DataResult:
    err = ReliabilityError(
        status="unavailable",
        code="DATA_SOURCE_UNAVAILABLE",
        message="down",
        domain="price_history",
        market="us",
        http_status=503,
        retry_after_seconds=120,
    )
    return _direct_result(
        status="unavailable", result_kind=ResultKind.EMPTY, source="none", error=err
    )


def partial_result(*, missing_symbols: list[str]) -> DataResult:
    return _direct_result(
        status="fresh",
        result_kind=ResultKind.PARTIAL,
        source="yfinance",
        missing_symbols=tuple(missing_symbols),
    )


# --- Realtime quotes batch fakes --------------------------------------------

DEFAULT_FRESH_FETCHED_AT = "2026-04-17T09:35:00Z"


def gateway_with_realtime_quotes_batch() -> FakeGateway:
    result = DataResult(
        status="fresh",
        result_kind=ResultKind.DATA,
        cache_key="realtime_quotes:us",
        source="yfinance",
        served_from_cache=False,
        fetched_at=_parse_fetched_at(DEFAULT_FRESH_FETCHED_AT),
        age_seconds=0,
        degraded_reason=None,
        missing_symbols=(),
        attempted_sources=(
            {"symbol": "AAA", "adapter": "yfinance", "outcome": "success"},
            {"symbol": "BBB", "adapter": "yfinance", "outcome": "success"},
        ),
        data=[
            {"symbol": "AAA", "price": 101.5, "change_pct": 0.42},
            {"symbol": "BBB", "price": 57.0, "change_pct": -0.11},
        ],
        error=None,
    )
    return FakeGateway(single_result=result)


def gateway_with_partial_quotes_batch() -> FakeGateway:
    result = DataResult(
        status="stale",
        result_kind=ResultKind.PARTIAL,
        cache_key="realtime_quotes:us",
        source="yfinance",
        served_from_cache=False,
        fetched_at=_parse_fetched_at(DEFAULT_FETCHED_AT),
        age_seconds=DEFAULT_STALE_AGE_SECONDS,
        degraded_reason="quote provider returned partial batch",
        missing_symbols=("BBB",),
        attempted_sources=(
            {"symbol": "AAA", "adapter": "yfinance", "outcome": "success"},
            {"symbol": "BBB", "adapter": "yfinance", "outcome": "empty"},
        ),
        data=[
            {"symbol": "AAA", "price": 101.5, "change_pct": 0.42},
        ],
        error=None,
    )
    return FakeGateway(single_result=result)


def gateway_returning_stale_history(symbol: str = "AAPL") -> FakeGateway:
    """Alias for :func:`gateway_returning_stale_analysis_data`.

    Used by agent-tool tests that want a stale price_history gateway fake.
    """
    return gateway_returning_stale_analysis_data(symbol=symbol)


def gateway_returning_stale_analysis_data(symbol: str = "AAPL") -> FakeGateway:
    """Gateway fake that returns a stale price_history DataResult with a realistic DataFrame.

    Used by CLI reliability tests to assert the stale-cache warning path.
    """
    return FakeGateway(
        single_result=build_result(
            domain="price_history",
            status="stale",
            result_kind="data",
            source="cache:akshare",
            served_from_cache=True,
            age_seconds=DEFAULT_STALE_AGE_SECONDS,
            symbol=symbol,
            attempted_sources=[
                {"adapter": "akshare", "outcome": "error", "reason": "ConnectionError"},
            ],
        )
    )


def gateway_with_unavailable_quotes_batch() -> FakeGateway:
    err = ReliabilityError(
        status="unavailable",
        code="DATA_SOURCE_UNAVAILABLE",
        message="quote provider unavailable",
        domain="realtime_quotes",
        market="us",
        symbol=None,
        missing_symbols=("AAA", "BBB"),
        attempted_sources=(),
        retry_after_seconds=DEFAULT_RETRY_AFTER_SECONDS,
        http_status=503,
    )
    result = DataResult(
        status="unavailable",
        result_kind=ResultKind.EMPTY,
        cache_key="realtime_quotes:us",
        source="none",
        served_from_cache=False,
        fetched_at=None,
        age_seconds=None,
        degraded_reason=None,
        missing_symbols=("AAA", "BBB"),
        attempted_sources=(),
        data=None,
        error=err,
    )
    return FakeGateway(single_result=result)
