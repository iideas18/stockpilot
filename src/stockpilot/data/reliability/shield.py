"""Reliability shield: cache + failover + health orchestration.

The shield sits between the gateway (request builder) and the adapters:

1. Validates that an explicit ``adapter_name`` is allowed by the registry.
2. Checks the cache for a fresh entry; returns it without calling live.
3. Walks the registry-ordered list of adapters. For each:
   - Respects source-health (skips cooling-down sources unless a probe is due).
   - Calls ``fetch_live(adapter, request)`` supplied by the gateway.
   - Classifies the payload per-domain (valid data / valid empty / invalid empty).
   - On success, caches and returns a ``fresh`` DataResult.
   - On transient error, records the failure and falls through to the next adapter.
4. If all adapters fail, serves stale cache when available, else returns a
   normalized ``DATA_SOURCE_UNAVAILABLE`` envelope.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable

import pandas as pd

from stockpilot.config import get_settings
from stockpilot.data.adapters import BaseDataAdapter, Market
from stockpilot.data.errors import (
    CallerDataError,
    CoverageEmptyData,
    DisabledDataSourceError,
    SourceResponseError,
)
from stockpilot.data.manager import DataManager
from stockpilot.data.reliability.registry import SourceRegistry
from stockpilot.data.reliability.store import ReliabilityStore, _utc_now_iso, _add_seconds
from stockpilot.data.reliability.types import (
    CacheClass,
    DataResult,
    DomainId,
    DomainRequest,
    ReliabilityError,
    ResultKind,
    SourceHealthState,
)

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------- helpers


_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _serialize_date(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def make_cache_key(request: DomainRequest) -> str:
    """Deterministic cache key built from normalized request params."""

    payload = {
        "domain": request.domain.value if isinstance(request.domain, DomainId) else str(request.domain),
        "market": request.market,
        "symbol": request.symbol,
        "symbols": sorted(list(request.symbols or ())),
        "keyword": request.keyword,
        "start_date": _serialize_date(request.start_date),
        "end_date": _serialize_date(request.end_date),
        "timeframe": request.timeframe,
        "adjust": request.adjust,
        "adapter_name": request.adapter_name,
    }
    return json.dumps(payload, sort_keys=True)


def _hash_subject_key(cache_key: str) -> str:
    return hashlib.sha256(cache_key.encode("utf-8")).hexdigest()[:24]


def _is_empty_payload(domain: DomainId, payload: Any) -> bool:
    if payload is None:
        return True
    if isinstance(payload, pd.DataFrame):
        return payload.empty
    if isinstance(payload, (list, tuple, dict, set)):
        return len(payload) == 0
    return False


def _payload_to_jsonable(payload: Any) -> tuple[str, Any]:
    """Return (payload_format, jsonable_payload) ready for the store."""

    if isinstance(payload, pd.DataFrame):
        return "records", payload.to_dict(orient="records")
    if isinstance(payload, dict):
        return "json", payload
    if isinstance(payload, list):
        return "list", payload
    return "json", payload


def _payload_from_stored(payload_format: str, body: Any) -> Any:
    if payload_format == "records":
        try:
            return pd.DataFrame(body or [])
        except Exception:
            return pd.DataFrame()
    return body


# ------------------------------------------------------------------ market now


_MARKET_TZS = {
    "a_share": timezone(timedelta(hours=8)),
    "hk": timezone(timedelta(hours=8)),
    "us": timezone(timedelta(hours=-4)),  # approximate; America/New_York EDT
}


def _market_tz(market: str) -> timezone:
    return _MARKET_TZS.get(str(market), timezone.utc)


# ----------------------------------------------------------------------- class


class ReliabilityShield:
    """Orchestrates cache / failover / health for the data gateway."""

    def __init__(
        self,
        data_manager: DataManager,
        registry: SourceRegistry,
        store: ReliabilityStore,
    ) -> None:
        self.data_manager = data_manager
        self.registry = registry
        self.store = store
        try:
            settings = get_settings()
            self._cache_windows = dict(settings.data.reliability.cache_windows)
            self._cooldown_seconds = int(
                settings.data.reliability.health.get("cooldown_seconds", 120)
            )
        except Exception:
            self._cache_windows = {
                "live_quote": {"fresh_seconds": 15, "stale_seconds": 120},
                "session_series": {"fresh_seconds": 60, "stale_seconds": 3600},
                "historical_series": {"fresh_seconds": 3600, "stale_seconds": 30 * 86400},
                "reference_data": {"fresh_seconds": 3600, "stale_seconds": 7 * 86400},
            }
            self._cooldown_seconds = 120

    # --------------------------------------------------------------- time zone

    def _market_now(self, market: str, now_override: str | None = None) -> datetime:
        if now_override:
            parsed = datetime.fromisoformat(now_override)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_market_tz(market))
            return parsed.astimezone(_market_tz(market))
        return datetime.now(tz=_market_tz(market))

    # ------------------------------------------------------------- classifier

    def classify_cache_class(
        self,
        domain: DomainId,
        market: str,
        start_date: date | None = None,
        end_date: date | None = None,
        now_override: str | None = None,
    ) -> CacheClass:
        if domain == DomainId.REALTIME_QUOTE or domain == DomainId.REALTIME_QUOTES:
            return CacheClass.LIVE_QUOTE
        if domain in (DomainId.STOCK_LIST, DomainId.SEARCH, DomainId.FUNDAMENTAL_DATA):
            return CacheClass.REFERENCE_DATA
        if domain != DomainId.PRICE_HISTORY:
            return CacheClass.HISTORICAL_SERIES

        try:
            now = self._market_now(market, now_override)
        except Exception:
            return CacheClass.HISTORICAL_SERIES

        today_local = now.date()
        end = end_date if isinstance(end_date, date) else None
        if end is None or end < today_local:
            return CacheClass.HISTORICAL_SERIES

        # end_date >= today: check if current time is within market session.
        weekday = now.weekday()
        if weekday >= 5:  # Sat/Sun
            return CacheClass.HISTORICAL_SERIES
        minutes = now.hour * 60 + now.minute
        if str(market) == "a_share":
            in_session = (9 * 60 + 15) <= minutes <= (15 * 60 + 5)
        elif str(market) == "us":
            in_session = (9 * 60 + 30) <= minutes <= (16 * 60 + 10)
        else:
            in_session = (9 * 60) <= minutes <= (16 * 60 + 30)
        return CacheClass.SESSION_SERIES if in_session else CacheClass.HISTORICAL_SERIES

    # --------------------------------------------------------- public execute

    def execute(
        self,
        request: DomainRequest,
        fetch_live: Callable[[BaseDataAdapter, DomainRequest], Any],
    ) -> DataResult:
        domain_key = request.domain.value
        allowlist = self.registry.get_adapter_order(request.domain, request.market)

        # 1. Validate explicit adapter_name.
        if request.adapter_name and request.adapter_name != "auto":
            if request.adapter_name not in allowlist:
                return self._invalid_request(
                    request,
                    f"adapter '{request.adapter_name}' is not allowed for "
                    f"{domain_key}/{request.market}",
                )
            adapter_order = [request.adapter_name]
        else:
            adapter_order = list(allowlist)

        cache_key = make_cache_key(request)

        # 2. Fresh cache read.
        now_iso = _utc_now_iso()
        cached = None
        try:
            cached = self.store.get_cache_entry(cache_key, now=now_iso)
        except Exception:  # pragma: no cover - defensive
            cached = None

        if cached is not None and cached.status == "fresh":
            return self._fresh_from_cache(request, cached, cache_key)

        # 3. Walk adapters.
        attempted: list[dict[str, Any]] = []
        if not adapter_order:
            return self._unavailable(request, cache_key, attempted, cached)

        for adapter_name in adapter_order:
            try:
                adapter = self.data_manager.get_adapter(name=adapter_name)
            except Exception:
                attempted.append({"adapter": adapter_name, "outcome": "not_registered"})
                continue

            health = self.store.get_source_health(adapter_name, domain_key, request.market)
            if health.state == SourceHealthState.COOLING_DOWN:
                if not self.store.begin_probe(adapter_name, domain_key, request.market, now_iso):
                    attempted.append({"adapter": adapter_name, "outcome": "cooling_down"})
                    continue
            if health.state == SourceHealthState.DISABLED:
                attempted.append({"adapter": adapter_name, "outcome": "disabled"})
                continue

            try:
                payload = fetch_live(adapter, request)
            except CallerDataError as exc:
                attempted.append({"adapter": adapter_name, "outcome": "caller_error"})
                return self._invalid_request(request, str(exc), attempted)
            except DisabledDataSourceError:
                attempted.append({"adapter": adapter_name, "outcome": "disabled"})
                continue
            except CoverageEmptyData:
                # Fundamentals coverage gap: valid semantics, don't fall through.
                self.store.record_source_success(
                    adapter_name, domain_key, request.market, now_iso
                )
                attempted.append({"adapter": adapter_name, "outcome": "empty"})
                return self._fresh_empty(
                    request, adapter_name, cache_key, attempted, payload=None
                )
            except (SourceResponseError, ConnectionError, TimeoutError, OSError) as exc:
                error_type = type(exc).__name__
                attempted.append(
                    {"adapter": adapter_name, "outcome": "error", "error": error_type}
                )
                self.store.record_source_failure(
                    adapter_name, domain_key, request.market, "transient_source_error", now_iso
                )
                logger.warning(
                    "Adapter %s failed for %s/%s: %s",
                    adapter_name,
                    domain_key,
                    request.market,
                    exc,
                )
                continue

            # Handle empty payload per-domain.
            if _is_empty_payload(request.domain, payload):
                policy = self._empty_policy(request.domain)
                if policy == "fresh_empty":
                    self.store.record_source_success(
                        adapter_name, domain_key, request.market, now_iso
                    )
                    attempted.append({"adapter": adapter_name, "outcome": "empty"})
                    return self._fresh_empty(
                        request, adapter_name, cache_key, attempted, payload=payload
                    )
                # policy == "source_error": fall through.
                attempted.append({"adapter": adapter_name, "outcome": "empty_invalid"})
                self.store.record_source_failure(
                    adapter_name, domain_key, request.market, "empty_payload", now_iso
                )
                continue

            # Success path.
            self.store.record_source_success(
                adapter_name, domain_key, request.market, now_iso
            )
            attempted.append({"adapter": adapter_name, "outcome": "success"})
            return self._fresh_success(
                request, adapter_name, cache_key, attempted, payload
            )

        # 4. All adapters exhausted — try stale cache.
        if cached is not None and cached.status == "stale":
            return self._stale_from_cache(request, cached, cache_key, attempted)

        return self._unavailable(request, cache_key, attempted, cached)

    # -------------------------------------------------------------- policies

    @staticmethod
    def _empty_policy(domain: DomainId) -> str:
        # "fresh_empty" → empty payload is a valid terminal answer.
        # "source_error" → treat as a transient source error (fallback).
        if domain == DomainId.PRICE_HISTORY:
            return "fresh_empty"
        if domain == DomainId.SEARCH:
            return "fresh_empty"
        if domain == DomainId.FUNDAMENTAL_DATA:
            return "source_error"
        if domain == DomainId.REALTIME_QUOTE:
            return "source_error"
        if domain == DomainId.REALTIME_QUOTES:
            return "source_error"
        if domain == DomainId.STOCK_LIST:
            return "source_error"
        return "source_error"

    # ------------------------------------------------------------- builders

    def _cache_windows_for(self, request: DomainRequest) -> tuple[int, int]:
        cache_class = request.cache_class or CacheClass.REFERENCE_DATA
        window = self._cache_windows.get(cache_class.value, {})
        fresh = int(window.get("fresh_seconds", 300))
        stale = int(window.get("stale_seconds", 3600))
        return fresh, stale

    def _write_cache(
        self,
        request: DomainRequest,
        adapter_name: str,
        cache_key: str,
        payload: Any,
        result_kind: ResultKind,
        now_iso: str,
    ) -> None:
        fresh_s, stale_s = self._cache_windows_for(request)
        fresh_until = _add_seconds(now_iso, fresh_s)
        stale_until = _add_seconds(now_iso, stale_s)
        payload_format, body = _payload_to_jsonable(payload)
        try:
            self.store.put_cache_entry(
                cache_key=cache_key,
                domain=request.domain.value,
                market=request.market,
                adapter=adapter_name,
                request_params_json=cache_key,
                subject_key=_hash_subject_key(cache_key),
                payload_format=payload_format,
                payload=body,
                result_kind=result_kind.value,
                meta={},
                fetched_at=now_iso,
                fresh_until=fresh_until,
                stale_until=stale_until,
            )
        except Exception:  # pragma: no cover - defensive
            pass

    def _fresh_success(
        self,
        request: DomainRequest,
        adapter_name: str,
        cache_key: str,
        attempted: list[dict[str, Any]],
        payload: Any,
    ) -> DataResult:
        now_iso = _utc_now_iso()
        self._write_cache(
            request, adapter_name, cache_key, payload, ResultKind.DATA, now_iso
        )
        fetched_at = datetime.now(tz=timezone.utc)
        return DataResult(
            status="fresh",
            result_kind=ResultKind.DATA,
            cache_key=cache_key,
            source=adapter_name,
            served_from_cache=False,
            fetched_at=fetched_at,
            age_seconds=0,
            degraded_reason=None,
            attempted_sources=tuple(attempted),
            data=payload,
        )

    def _fresh_empty(
        self,
        request: DomainRequest,
        adapter_name: str,
        cache_key: str,
        attempted: list[dict[str, Any]],
        payload: Any,
    ) -> DataResult:
        now_iso = _utc_now_iso()
        # Cache the empty answer so we don't hammer the source.
        cache_payload = payload if payload is not None else self._empty_placeholder(request.domain)
        self._write_cache(
            request, adapter_name, cache_key, cache_payload, ResultKind.EMPTY, now_iso
        )
        fetched_at = datetime.now(tz=timezone.utc)
        return DataResult(
            status="fresh",
            result_kind=ResultKind.EMPTY,
            cache_key=cache_key,
            source=adapter_name,
            served_from_cache=False,
            fetched_at=fetched_at,
            age_seconds=0,
            degraded_reason=None,
            attempted_sources=tuple(attempted),
            data=payload if payload is not None else self._empty_placeholder(request.domain),
        )

    @staticmethod
    def _empty_placeholder(domain: DomainId) -> Any:
        if domain in (DomainId.PRICE_HISTORY, DomainId.STOCK_LIST, DomainId.REALTIME_QUOTES):
            return pd.DataFrame()
        if domain == DomainId.SEARCH:
            return []
        return {}

    def _fresh_from_cache(
        self,
        request: DomainRequest,
        cached: Any,
        cache_key: str,
    ) -> DataResult:
        payload = _payload_from_stored(cached.payload_format, cached.payload)
        try:
            fetched_at = datetime.strptime(cached.fetched_at, _ISO_FMT).replace(
                tzinfo=timezone.utc
            )
        except Exception:
            fetched_at = None
        age = None
        if fetched_at is not None:
            age = int((datetime.now(tz=timezone.utc) - fetched_at).total_seconds())
        result_kind = ResultKind(cached.result_kind) if cached.result_kind in {rk.value for rk in ResultKind} else ResultKind.DATA
        return DataResult(
            status="fresh",
            result_kind=result_kind,
            cache_key=cache_key,
            source=f"cache:{cached.adapter}",
            served_from_cache=True,
            fetched_at=fetched_at,
            age_seconds=age,
            degraded_reason=None,
            attempted_sources=(
                {"adapter": cached.adapter, "outcome": "cache_hit"},
            ),
            data=payload,
        )

    def _stale_from_cache(
        self,
        request: DomainRequest,
        cached: Any,
        cache_key: str,
        attempted: list[dict[str, Any]],
    ) -> DataResult:
        payload = _payload_from_stored(cached.payload_format, cached.payload)
        try:
            fetched_at = datetime.strptime(cached.fetched_at, _ISO_FMT).replace(
                tzinfo=timezone.utc
            )
        except Exception:
            fetched_at = None
        age = None
        if fetched_at is not None:
            age = int((datetime.now(tz=timezone.utc) - fetched_at).total_seconds())
        result_kind = ResultKind(cached.result_kind) if cached.result_kind in {rk.value for rk in ResultKind} else ResultKind.DATA
        stale_attempts = tuple(attempted) + (
            {"adapter": cached.adapter, "outcome": "stale_cache_hit"},
        )
        return DataResult(
            status="stale",
            result_kind=result_kind,
            cache_key=cache_key,
            source=f"cache:{cached.adapter}",
            served_from_cache=True,
            fetched_at=fetched_at,
            age_seconds=age,
            degraded_reason="live sources unavailable; serving cached payload",
            attempted_sources=stale_attempts,
            data=payload,
        )

    def _invalid_request(
        self,
        request: DomainRequest,
        message: str,
        attempted: list[dict[str, Any]] | None = None,
    ) -> DataResult:
        err = ReliabilityError(
            status="invalid_request",
            code="DATA_REQUEST_INVALID",
            message=message,
            domain=request.domain.value,
            market=request.market,
            symbol=request.symbol,
            http_status=400,
            attempted_sources=tuple(attempted or ()),
        )
        return DataResult(
            status="invalid_request",
            result_kind=ResultKind.EMPTY,
            cache_key=make_cache_key(request),
            source="",
            served_from_cache=False,
            fetched_at=None,
            age_seconds=None,
            degraded_reason=None,
            attempted_sources=tuple(attempted or ()),
            error=err,
        )

    def _unavailable(
        self,
        request: DomainRequest,
        cache_key: str,
        attempted: list[dict[str, Any]],
        cached: Any | None,
    ) -> DataResult:
        cache_state = None
        if cached is not None:
            cache_state = cached.status
        err = ReliabilityError(
            status="unavailable",
            code="DATA_SOURCE_UNAVAILABLE",
            message="No configured adapter succeeded and no usable cache was available.",
            domain=request.domain.value,
            market=request.market,
            symbol=request.symbol,
            attempted_sources=tuple(attempted),
            cache_state=cache_state,
            retry_after_seconds=self._cooldown_seconds,
            http_status=503,
        )
        return DataResult(
            status="unavailable",
            result_kind=ResultKind.EMPTY,
            cache_key=cache_key,
            source="",
            served_from_cache=False,
            fetched_at=None,
            age_seconds=None,
            degraded_reason=None,
            attempted_sources=tuple(attempted),
            error=err,
        )
