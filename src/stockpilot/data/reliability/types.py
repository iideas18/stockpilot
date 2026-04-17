"""Core typed primitives for the data reliability layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Any, Generic, TypeVar


T = TypeVar("T")


class DomainId(str, Enum):
    PRICE_HISTORY = "price_history"
    REALTIME_QUOTE = "realtime_quote"
    REALTIME_QUOTES = "realtime_quotes"
    FUNDAMENTAL_DATA = "fundamental_data"
    STOCK_LIST = "stock_list"
    SEARCH = "search"


class CacheClass(str, Enum):
    LIVE_QUOTE = "live_quote"
    SESSION_SERIES = "session_series"
    HISTORICAL_SERIES = "historical_series"
    REFERENCE_DATA = "reference_data"


class SourceHealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    COOLING_DOWN = "cooling_down"
    RECOVERING = "recovering"
    DISABLED = "disabled"


class ResultKind(str, Enum):
    DATA = "data"
    EMPTY = "empty"
    PARTIAL = "partial"


@dataclass(frozen=True)
class DomainRequest:
    domain: DomainId
    market: str
    symbol: str | None = None
    symbols: tuple[str, ...] = ()
    keyword: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    timeframe: str | None = None
    adjust: str = "qfq"
    cache_class: CacheClass | None = None
    adapter_name: str = "auto"
    require_complete: bool = False


@dataclass(frozen=True)
class ReliabilityError:
    status: str
    code: str
    message: str
    domain: str
    market: str
    symbol: str | None = None
    missing_symbols: tuple[str, ...] = ()
    attempted_sources: tuple[dict[str, Any], ...] = ()
    cache_state: str | None = None
    retry_after_seconds: int | None = None
    http_status: int = 503

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "code": self.code,
            "message": self.message,
            "domain": self.domain,
            "market": self.market,
            "symbol": self.symbol,
            "missing_symbols": list(self.missing_symbols),
            "attempted_sources": [dict(item) for item in self.attempted_sources],
            "cache_state": self.cache_state,
            "retry_after_seconds": self.retry_after_seconds,
            "http_status": self.http_status,
        }


@dataclass(frozen=True)
class CacheEntry:
    cache_key: str
    domain: str
    market: str
    symbol: str | None
    cache_class: str
    source: str
    fetched_at: datetime
    payload: Any
    result_kind: ResultKind = ResultKind.DATA
    missing_symbols: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceHealth:
    adapter: str
    domain: str
    market: str
    state: SourceHealthState
    consecutive_errors: int = 0
    consecutive_successes: int = 0
    last_error: str | None = None
    last_error_at: datetime | None = None
    cooldown_until: datetime | None = None


@dataclass
class DataResult(Generic[T]):
    status: str
    result_kind: ResultKind
    cache_key: str
    source: str
    served_from_cache: bool
    fetched_at: datetime | None
    age_seconds: int | None
    degraded_reason: str | None
    missing_symbols: tuple[str, ...] = ()
    attempted_sources: tuple[dict[str, Any], ...] = ()
    data: T | None = None
    error: ReliabilityError | None = None

    def to_status_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "result_kind": self.result_kind.value,
            "source": self.source,
            "served_from_cache": self.served_from_cache,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "age_seconds": self.age_seconds,
            "degraded_reason": self.degraded_reason,
            "missing_symbols": list(self.missing_symbols),
            "attempted_sources": [dict(item) for item in self.attempted_sources],
        }
