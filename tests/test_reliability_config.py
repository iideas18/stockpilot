from __future__ import annotations

from datetime import datetime

from stockpilot.config import get_settings
from stockpilot.data.reliability.types import (
    CacheClass,
    DataResult,
    DomainId,
    ResultKind,
    SourceHealthState,
)


def test_reliability_settings_defaults(monkeypatch):
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.data.reliability.enabled is True
    assert settings.data.reliability.sqlite_path.endswith("stockpilot_reliability.sqlite3")
    assert settings.data.reliability.source_order["price_history"]["a_share"] == ["akshare"]
    assert settings.data.reliability.source_order["price_history"]["us"] == ["yfinance"]
    assert settings.data.reliability.source_order["realtime_quotes"]["a_share"] == ["akshare"]
    assert settings.data.reliability.cache_windows["live_quote"]["fresh_seconds"] == 15
    assert settings.data.reliability.cache_windows["live_quote"]["stale_seconds"] == 120
    assert settings.data.reliability.cache_windows["historical_series"]["stale_seconds"] == 30 * 24 * 60 * 60
    assert settings.data.reliability.health["degrade_after_errors"] == 2
    assert settings.data.reliability.health["cool_down_after_errors"] == 3
    assert settings.data.reliability.health["cooldown_seconds"] == 120
    assert settings.data.reliability.health["recover_after_successes"] == 2


def test_domain_ids_and_result_kinds_are_canonical():
    assert DomainId.PRICE_HISTORY.value == "price_history"
    assert CacheClass.SESSION_SERIES.value == "session_series"
    assert ResultKind.PARTIAL.value == "partial"
    assert SourceHealthState.COOLING_DOWN.value == "cooling_down"


def test_data_result_to_status_dict_matches_api_contract():
    result = DataResult(
        status="stale",
        result_kind=ResultKind.DATA,
        cache_key="price:auto",
        source="cache:akshare",
        served_from_cache=True,
        fetched_at=datetime(2026, 4, 17, 9, 0, 0),
        age_seconds=600,
        degraded_reason="live source unavailable",
        missing_symbols=("MSFT",),
        attempted_sources=({"adapter": "akshare", "outcome": "error"},),
        data=None,
        error=None,
    )
    status = result.to_status_dict()
    assert status["status"] == "stale"
    assert status["missing_symbols"] == ["MSFT"]
