import sqlite3
from stockpilot.data.reliability.store import ReliabilityStore


def test_store_round_trips_cache_and_health(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    store.put_cache_entry(
        cache_key="price:abc",
        domain="price_history",
        market="a_share",
        request_params_json='{"adapter_name":"auto","domain":"price_history","market":"a_share","symbol":"000001"}',
        subject_key="000001",
        payload_format="json",
        payload={"rows": [1]},
        result_kind="data",
        meta={"missing_symbols": []},
        fetched_at="2026-04-17T09:00:00Z",
        fresh_until="2026-04-17T09:05:00Z",
        stale_until="2026-04-17T09:30:00Z",
        adapter="akshare",
    )
    cache_entry = store.get_cache_entry("price:abc")
    health = store.record_source_failure(
        "akshare", "price_history", "a_share",
        "transient_source_error", "2026-04-17T09:01:00Z",
    )
    assert cache_entry.result_kind == "data"
    assert cache_entry.subject_key == "000001"
    assert health.consecutive_errors == 1


def test_begin_probe_is_compare_and_set(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    # Drive state to cooling_down so begin_probe can engage.
    store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:00:00Z")
    store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:01:00Z")
    store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:02:00Z")
    assert store.begin_probe("akshare", "price_history", "a_share", "2026-04-17T09:04:01Z") is True
    # Second call 30s later: probe_started_at is set, gap < min_probe_gap → False.
    assert store.begin_probe("akshare", "price_history", "a_share", "2026-04-17T09:04:31Z") is False


def test_store_transitions_from_cooling_down_to_recovering_and_healthy(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:00:00Z")
    store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:01:00Z")
    store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:02:00Z")
    assert store.get_source_health("akshare", "price_history", "a_share").state == "cooling_down"
    assert store.begin_probe("akshare", "price_history", "a_share", "2026-04-17T09:04:01Z") is True
    store.record_source_success("akshare", "price_history", "a_share", "2026-04-17T09:04:02Z")
    health = store.record_source_success("akshare", "price_history", "a_share", "2026-04-17T09:04:03Z")
    assert health.state == "healthy"


def test_store_persists_and_computes_fresh_vs_stale_across_restarts(tmp_path):
    db_path = tmp_path / "reliability.sqlite3"
    first = ReliabilityStore(db_path)
    first.put_cache_entry(
        cache_key="price:abc",
        domain="price_history",
        market="a_share",
        request_params_json='{"adapter_name":"auto","domain":"price_history","market":"a_share","symbol":"000001"}',
        subject_key="000001",
        payload_format="json",
        payload={"rows": [1]},
        result_kind="data",
        meta={"missing_symbols": []},
        fetched_at="2026-04-17T09:00:00Z",
        fresh_until="2026-04-17T09:05:00Z",
        stale_until="2026-04-17T09:30:00Z",
        adapter="akshare",
    )
    second = ReliabilityStore(db_path)
    assert second.get_cache_entry("price:abc", now="2026-04-17T09:02:00Z").status == "fresh"
    assert second.get_cache_entry("price:abc", now="2026-04-17T09:20:00Z").status == "stale"


def test_store_fails_open_when_sqlite_access_breaks(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    monkeypatch.setattr(store, "_execute", lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    assert store.get_cache_entry("missing") is None


def test_degraded_promotes_to_healthy_on_single_success(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:00:00Z")
    health = store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:01:00Z")
    assert health.state.value == "degraded"
    health = store.record_source_success("akshare", "price_history", "a_share", "2026-04-17T09:02:00Z")
    assert health.state.value == "healthy"


def test_put_cache_entry_upserts_on_duplicate_key(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    common = dict(
        cache_key="price:dup",
        domain="price_history",
        market="a_share",
        request_params_json='{}',
        subject_key="000001",
        payload_format="json",
        result_kind="data",
        meta={},
        fetched_at="2026-04-17T09:00:00Z",
        fresh_until="2026-04-17T09:05:00Z",
        stale_until="2026-04-17T09:30:00Z",
        adapter="akshare",
    )
    store.put_cache_entry(payload={"v": 1}, **common)
    store.put_cache_entry(payload={"v": 2}, **common)
    entry = store.get_cache_entry("price:dup", now="2026-04-17T09:01:00Z")
    assert entry.payload == {"v": 2}
    row = store._execute(
        "SELECT COUNT(*) AS c FROM cache_entries WHERE cache_key=?",
        ("price:dup",),
        fetch="one",
    )
    assert row["c"] == 1


def test_payload_list_round_trips(tmp_path):
    import json
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    payload = [{"a": 1}, {"a": 2}]
    store.put_cache_entry(
        cache_key="price:list",
        domain="price_history",
        market="a_share",
        request_params_json='{}',
        subject_key="000001",
        payload_format="json",
        payload=payload,
        result_kind="data",
        meta={},
        fetched_at="2026-04-17T09:00:00Z",
        fresh_until="2026-04-17T09:05:00Z",
        stale_until="2026-04-17T09:30:00Z",
        adapter="akshare",
    )
    entry = store.get_cache_entry("price:list", now="2026-04-17T09:01:00Z")
    assert entry.payload == payload
    # Also confirm JSON round-trip behavior matches deserialization.
    assert json.loads(json.dumps(entry.payload)) == payload


def test_writers_fail_open_when_execute_raises(tmp_path, monkeypatch):
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    monkeypatch.setattr(store, "_execute", lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("locked")))
    # None of these should raise.
    store.put_cache_entry(
        cache_key="price:x",
        domain="price_history",
        market="a_share",
        request_params_json='{}',
        subject_key="000001",
        payload_format="json",
        payload={"v": 1},
        result_kind="data",
        meta={},
        fetched_at="2026-04-17T09:00:00Z",
        fresh_until="2026-04-17T09:05:00Z",
        stale_until="2026-04-17T09:30:00Z",
        adapter="akshare",
    )
    store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:01:00Z")
    store.record_source_success("akshare", "price_history", "a_share", "2026-04-17T09:02:00Z")
    assert store.begin_probe("akshare", "price_history", "a_share", "2026-04-17T09:03:00Z") is False
