"""SQLite-backed reliability store: cache entries + source health state machine.

All SQL goes through `_execute` so the store can fail open if the database
becomes unavailable (public getters return None, writers silently no-op).
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from stockpilot.config import get_settings
from stockpilot.data.reliability.types import SourceHealth, SourceHealthState


_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _utc_now_iso() -> str:
    return datetime.utcnow().strftime(_ISO_FMT)


def _parse_iso(value: str) -> datetime:
    # Accept both Z-suffixed and plain ISO strings.
    if value.endswith("Z"):
        return datetime.strptime(value, _ISO_FMT)
    return datetime.fromisoformat(value)


def _add_seconds(iso: str, seconds: int) -> str:
    return (_parse_iso(iso) + timedelta(seconds=seconds)).strftime(_ISO_FMT)


@dataclass
class StoredCacheEntry:
    cache_key: str
    domain: str
    market: str
    adapter: str
    request_params_json: str
    subject_key: str
    result_kind: str
    payload_format: str
    payload: Any
    meta: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = ""
    fresh_until: str = ""
    stale_until: str = ""
    status: str = ""


class ReliabilityStore:
    """Persists cache entries and source-health for the reliability gateway."""

    _MIN_PROBE_GAP_SECONDS = 60

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.stateless = False
        self._thresholds = self._load_thresholds()
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._init_schema()
        except sqlite3.Error:
            self.stateless = True

    # ------------------------------------------------------------------ infra

    def _load_thresholds(self) -> dict[str, int]:
        try:
            return dict(get_settings().data.reliability.health)
        except Exception:
            return {
                "degrade_after_errors": 2,
                "cool_down_after_errors": 3,
                "cooldown_seconds": 120,
                "recover_after_successes": 2,
            }

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _execute(
        self,
        sql: str,
        params: Iterable[Any] = (),
        *,
        fetch: str = "none",
    ) -> Any:
        conn = self._connect()
        try:
            cur = conn.execute(sql, tuple(params))
            if fetch == "one":
                row = cur.fetchone()
                conn.commit()
                return row
            if fetch == "all":
                rows = cur.fetchall()
                conn.commit()
                return rows
            if fetch == "changes":
                changes = conn.total_changes
                conn.commit()
                return changes
            conn.commit()
            return None
        finally:
            conn.close()

    def _init_schema(self) -> None:
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS cache_entries (
                cache_key TEXT PRIMARY KEY,
                domain TEXT,
                market TEXT,
                adapter TEXT,
                request_params_json TEXT,
                subject_key TEXT,
                result_kind TEXT,
                payload_format TEXT,
                payload_body TEXT,
                payload_meta_json TEXT,
                fetched_at TEXT,
                fresh_until TEXT,
                stale_until TEXT
            )
            """
        )
        self._execute(
            """
            CREATE TABLE IF NOT EXISTS source_health (
                adapter TEXT,
                domain TEXT,
                market TEXT,
                state TEXT,
                consecutive_errors INTEGER DEFAULT 0,
                consecutive_successes INTEGER DEFAULT 0,
                last_success_at TEXT,
                last_failure_at TEXT,
                cooldown_until TEXT,
                last_error_type TEXT,
                probe_started_at TEXT,
                PRIMARY KEY(adapter, domain, market)
            )
            """
        )

    # ------------------------------------------------------------------ cache

    def put_cache_entry(
        self,
        *,
        cache_key: str,
        domain: str,
        market: str,
        request_params_json: str,
        subject_key: str,
        payload_format: str,
        payload: Any,
        result_kind: str,
        meta: dict[str, Any],
        fetched_at: str,
        fresh_until: str,
        stale_until: str,
        adapter: str,
    ) -> None:
        try:
            payload_body = json.dumps(payload)
            meta_json = json.dumps(meta or {})
            self._execute(
                """
                INSERT INTO cache_entries (
                    cache_key, domain, market, adapter, request_params_json,
                    subject_key, result_kind, payload_format, payload_body,
                    payload_meta_json, fetched_at, fresh_until, stale_until
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    domain=excluded.domain,
                    market=excluded.market,
                    adapter=excluded.adapter,
                    request_params_json=excluded.request_params_json,
                    subject_key=excluded.subject_key,
                    result_kind=excluded.result_kind,
                    payload_format=excluded.payload_format,
                    payload_body=excluded.payload_body,
                    payload_meta_json=excluded.payload_meta_json,
                    fetched_at=excluded.fetched_at,
                    fresh_until=excluded.fresh_until,
                    stale_until=excluded.stale_until
                """,
                (
                    cache_key,
                    domain,
                    market,
                    adapter,
                    request_params_json,
                    subject_key,
                    result_kind,
                    payload_format,
                    payload_body,
                    meta_json,
                    fetched_at,
                    fresh_until,
                    stale_until,
                ),
            )
        except sqlite3.Error:
            return None

    def get_cache_entry(
        self, cache_key: str, now: str | None = None
    ) -> StoredCacheEntry | None:
        try:
            row = self._execute(
                "SELECT * FROM cache_entries WHERE cache_key=?",
                (cache_key,),
                fetch="one",
            )
        except sqlite3.Error:
            return None
        if row is None:
            return None
        now_iso = now or _utc_now_iso()
        fresh_until = row["fresh_until"] or ""
        stale_until = row["stale_until"] or ""
        if now_iso <= fresh_until:
            status = "fresh"
        elif now_iso <= stale_until:
            status = "stale"
        else:
            status = "expired"
        try:
            payload = json.loads(row["payload_body"]) if row["payload_body"] else None
        except (TypeError, ValueError):
            payload = None
        try:
            meta = json.loads(row["payload_meta_json"]) if row["payload_meta_json"] else {}
        except (TypeError, ValueError):
            meta = {}
        return StoredCacheEntry(
            cache_key=row["cache_key"],
            domain=row["domain"] or "",
            market=row["market"] or "",
            adapter=row["adapter"] or "",
            request_params_json=row["request_params_json"] or "",
            subject_key=row["subject_key"] or "",
            result_kind=row["result_kind"] or "data",
            payload_format=row["payload_format"] or "json",
            payload=payload,
            meta=meta if isinstance(meta, dict) else {},
            fetched_at=row["fetched_at"] or "",
            fresh_until=fresh_until,
            stale_until=stale_until,
            status=status,
        )

    # ------------------------------------------------------------------ health

    def _get_health_row(self, adapter: str, domain: str, market: str):
        return self._execute(
            "SELECT * FROM source_health WHERE adapter=? AND domain=? AND market=?",
            (adapter, domain, market),
            fetch="one",
        )

    def _row_to_health(self, row, adapter: str, domain: str, market: str) -> SourceHealth:
        if row is None:
            return SourceHealth(
                adapter=adapter,
                domain=domain,
                market=market,
                state=SourceHealthState.HEALTHY,
            )
        state_value = row["state"] or SourceHealthState.HEALTHY.value
        try:
            state = SourceHealthState(state_value)
        except ValueError:
            state = SourceHealthState.HEALTHY
        last_fail = row["last_failure_at"]
        cooldown_until = row["cooldown_until"]
        return SourceHealth(
            adapter=adapter,
            domain=domain,
            market=market,
            state=state,
            consecutive_errors=int(row["consecutive_errors"] or 0),
            consecutive_successes=int(row["consecutive_successes"] or 0),
            last_error=row["last_error_type"],
            last_error_at=_parse_iso(last_fail) if last_fail else None,
            cooldown_until=_parse_iso(cooldown_until) if cooldown_until else None,
        )

    def get_source_health(self, adapter: str, domain: str, market: str) -> SourceHealth:
        try:
            row = self._get_health_row(adapter, domain, market)
        except sqlite3.Error:
            return SourceHealth(
                adapter=adapter,
                domain=domain,
                market=market,
                state=SourceHealthState.HEALTHY,
            )
        return self._row_to_health(row, adapter, domain, market)

    def _upsert_health(
        self,
        adapter: str,
        domain: str,
        market: str,
        *,
        state: str,
        consecutive_errors: int,
        consecutive_successes: int,
        last_success_at: str | None,
        last_failure_at: str | None,
        cooldown_until: str | None,
        last_error_type: str | None,
        probe_started_at: str | None,
    ) -> None:
        self._execute(
            """
            INSERT INTO source_health (
                adapter, domain, market, state, consecutive_errors,
                consecutive_successes, last_success_at, last_failure_at,
                cooldown_until, last_error_type, probe_started_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(adapter, domain, market) DO UPDATE SET
                state=excluded.state,
                consecutive_errors=excluded.consecutive_errors,
                consecutive_successes=excluded.consecutive_successes,
                last_success_at=excluded.last_success_at,
                last_failure_at=excluded.last_failure_at,
                cooldown_until=excluded.cooldown_until,
                last_error_type=excluded.last_error_type,
                probe_started_at=excluded.probe_started_at
            """,
            (
                adapter,
                domain,
                market,
                state,
                consecutive_errors,
                consecutive_successes,
                last_success_at,
                last_failure_at,
                cooldown_until,
                last_error_type,
                probe_started_at,
            ),
        )

    def record_source_failure(
        self,
        adapter: str,
        domain: str,
        market: str,
        error_type: str,
        at_iso: str,
    ) -> SourceHealth:
        try:
            row = self._get_health_row(adapter, domain, market)
            prev_errors = int(row["consecutive_errors"]) if row else 0
            last_success_at = row["last_success_at"] if row else None
            probe_started_at = row["probe_started_at"] if row else None
            cooldown_until = row["cooldown_until"] if row else None

            errors = prev_errors + 1
            successes = 0
            thresholds = self._thresholds
            if errors >= int(thresholds.get("cool_down_after_errors", 3)):
                state = SourceHealthState.COOLING_DOWN.value
                cooldown_until = _add_seconds(
                    at_iso, int(thresholds.get("cooldown_seconds", 120))
                )
                # Reset probe when entering a fresh cooling_down cycle.
                probe_started_at = None
            elif errors >= int(thresholds.get("degrade_after_errors", 2)):
                state = SourceHealthState.DEGRADED.value
            else:
                state = SourceHealthState.HEALTHY.value

            self._upsert_health(
                adapter,
                domain,
                market,
                state=state,
                consecutive_errors=errors,
                consecutive_successes=successes,
                last_success_at=last_success_at,
                last_failure_at=at_iso,
                cooldown_until=cooldown_until,
                last_error_type=error_type,
                probe_started_at=probe_started_at,
            )
            updated = self._get_health_row(adapter, domain, market)
            return self._row_to_health(updated, adapter, domain, market)
        except sqlite3.Error:
            return SourceHealth(
                adapter=adapter,
                domain=domain,
                market=market,
                state=SourceHealthState.HEALTHY,
            )

    def record_source_success(
        self,
        adapter: str,
        domain: str,
        market: str,
        at_iso: str,
    ) -> SourceHealth:
        try:
            row = self._get_health_row(adapter, domain, market)
            prev_successes = int(row["consecutive_successes"]) if row else 0
            prev_state = (row["state"] if row else None) or SourceHealthState.HEALTHY.value
            probe_started_at = row["probe_started_at"] if row else None
            last_failure_at = row["last_failure_at"] if row else None
            cooldown_until = row["cooldown_until"] if row else None
            last_error_type = row["last_error_type"] if row else None

            successes = prev_successes + 1
            errors = 0
            thresholds = self._thresholds
            recover_after = int(thresholds.get("recover_after_successes", 2))

            if prev_state == SourceHealthState.COOLING_DOWN.value and probe_started_at:
                state = SourceHealthState.RECOVERING.value
            elif prev_state == SourceHealthState.RECOVERING.value:
                if successes >= recover_after:
                    state = SourceHealthState.HEALTHY.value
                    probe_started_at = None
                    cooldown_until = None
                else:
                    state = SourceHealthState.RECOVERING.value
            elif prev_state == SourceHealthState.DEGRADED.value:
                state = SourceHealthState.HEALTHY.value
            elif prev_state == SourceHealthState.COOLING_DOWN.value:
                # Success without a probe: hold cooling_down.
                state = SourceHealthState.COOLING_DOWN.value
            else:
                state = SourceHealthState.HEALTHY.value

            self._upsert_health(
                adapter,
                domain,
                market,
                state=state,
                consecutive_errors=errors,
                consecutive_successes=successes,
                last_success_at=at_iso,
                last_failure_at=last_failure_at,
                cooldown_until=cooldown_until,
                last_error_type=last_error_type,
                probe_started_at=probe_started_at,
            )
            updated = self._get_health_row(adapter, domain, market)
            return self._row_to_health(updated, adapter, domain, market)
        except sqlite3.Error:
            return SourceHealth(
                adapter=adapter,
                domain=domain,
                market=market,
                state=SourceHealthState.HEALTHY,
            )

    # ------------------------------------------------------------------ probes

    def begin_probe(
        self, adapter: str, domain: str, market: str, at_iso: str
    ) -> bool:
        try:
            row = self._get_health_row(adapter, domain, market)
            if row is None:
                self._upsert_health(
                    adapter,
                    domain,
                    market,
                    state=SourceHealthState.HEALTHY.value,
                    consecutive_errors=0,
                    consecutive_successes=0,
                    last_success_at=None,
                    last_failure_at=None,
                    cooldown_until=None,
                    last_error_type=None,
                    probe_started_at=at_iso,
                )
                return True

            probe_started_at = row["probe_started_at"]
            if probe_started_at:
                try:
                    gap = (
                        _parse_iso(at_iso) - _parse_iso(probe_started_at)
                    ).total_seconds()
                except ValueError:
                    gap = self._MIN_PROBE_GAP_SECONDS + 1
                if gap < self._MIN_PROBE_GAP_SECONDS:
                    return False

            self._upsert_health(
                adapter,
                domain,
                market,
                state=row["state"] or SourceHealthState.HEALTHY.value,
                consecutive_errors=int(row["consecutive_errors"] or 0),
                consecutive_successes=int(row["consecutive_successes"] or 0),
                last_success_at=row["last_success_at"],
                last_failure_at=row["last_failure_at"],
                cooldown_until=row["cooldown_until"],
                last_error_type=row["last_error_type"],
                probe_started_at=at_iso,
            )
            return True
        except sqlite3.Error:
            return False
