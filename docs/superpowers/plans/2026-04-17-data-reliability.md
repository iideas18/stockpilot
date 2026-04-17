# Data Reliability Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local-first reliability layer for StockPilot data access so CLI, API, web, and agent flows can distinguish fresh, stale, not-found, and unavailable data without introducing new infrastructure.

**Architecture:** Keep the existing `DataManager` and adapters, then layer a new reliability package on top: typed data errors, a SQLite-backed reliability store, a source registry, and a `DataGateway` that returns structured status metadata. Phase 1 stays intentionally narrow: one configured live source per domain/market plus stale-cache fallback, with route-level aggregation for existing multi-symbol API flows and a minimal `realtime_quotes` watchlist/multi-quote touchpoint for the web UI.

**Tech Stack:** Python 3.10, sqlite3, pandas, FastAPI, Typer, Rich, pytest

---

## Planned File Structure

### New files

- `src/stockpilot/data/errors.py` — typed exceptions that adapters and the gateway share (`CallerDataError`, `DisabledDataSourceError`, `CoverageEmptyData`, `SourceResponseError`)
- `src/stockpilot/data/reliability/__init__.py` — package exports
- `src/stockpilot/data/reliability/types.py` — canonical domain IDs, enums, dataclasses for requests/results/errors/source health
- `src/stockpilot/data/reliability/store.py` — SQLite schema, cache reads/writes, health transitions, probe coordination, fail-open store behavior
- `src/stockpilot/data/reliability/registry.py` — static phase-1 source matrix and adapter selection rules
- `src/stockpilot/data/reliability/shield.py` — cache-keying, freshness evaluation, error-envelope construction, and single-request orchestration
- `src/stockpilot/data/reliability/gateway.py` — public `DataGateway` methods and route-level aggregation helpers
- `src/stockpilot/data/runtime.py` — `build_default_data_manager()` and `build_default_data_gateway()` so CLI/API/agents stop duplicating adapter registration
- `tests/reliability_fakes.py` — reusable fake gateway/results for API and CLI contract tests
- `tests/test_reliability_config.py` — config/type contract tests
- `tests/test_reliability_store.py` — SQLite store tests
- `tests/test_reliability_gateway.py` — registry/gateway/shield tests
- `tests/test_api_reliability.py` — API contract tests for `data_status`, 404/503 mapping, and route-level aggregation
- `tests/test_cli_reliability.py` — CLI/agent-tool tests for stale warnings and structured JSON payloads

### Modified files

- `config/settings.yaml` — default reliability config and phase-1 source matrix
- `src/stockpilot/config.py` — parse reliability config into `DataSettings`
- `src/stockpilot/data/__init__.py` — export gateway/runtime helpers
- `src/stockpilot/data/adapters/akshare_adapter.py` — raise typed data exceptions where the adapter can distinguish intent
- `src/stockpilot/data/adapters/yfinance_adapter.py` — same
- `src/stockpilot/api/main.py` — swap to `DataGateway`, attach `data_status`, aggregate multi-symbol status, map not-found vs unavailable
- `src/stockpilot/web/static/js/app.js` — format structured reliability errors and shared stale-data handling for the web UI
- `src/stockpilot/web/static/js/analysis.js` — render inline degraded/error state for analysis/chart flows
- `src/stockpilot/web/static/js/compare.js` — render inline degraded/error state for compare flows
- `src/stockpilot/web/static/js/portfolio.js` — render inline degraded/error state for portfolio optimization flows
- `src/stockpilot/cli.py` — use gateway in `analyze`, `search`, `agent`, `backtest`, and `chart`; surface stale warnings
- `src/stockpilot/agents/tools/agent_tools.py` — use gateway and include `data_status` in tool payloads
- `tests/test_api_v2.py` — update monkeypatch points if helper names change
- `tests/test_smoke.py` — smoke import for the new runtime/gateway layer

### Boundary notes

- Do **not** rewrite `DataManager` into the reliability layer; keep it as adapter lookup/legacy routing.
- Do **not** add multi-source live merging in this plan.
- Keep `api/main.py` thinner by moving new policy/state logic into the new reliability package instead of adding more branching in route handlers.

## Chunk 1: Reliability foundation

### Task 1: Add reliability config, typed errors, and status/result types

**Files:**
- Create: `src/stockpilot/data/errors.py`
- Create: `src/stockpilot/data/reliability/__init__.py`
- Create: `src/stockpilot/data/reliability/types.py`
- Modify: `src/stockpilot/config.py:87-167`
- Modify: `config/settings.yaml:12-35`
- Test: `tests/test_reliability_config.py`

- [ ] **Step 1: Write the failing test**

```python
from stockpilot.config import get_settings
from stockpilot.data.reliability.types import CacheClass, DomainId, ResultKind, SourceHealthState


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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_reliability_config.py::test_reliability_settings_defaults tests/test_reliability_config.py::test_domain_ids_and_result_kinds_are_canonical tests/test_reliability_config.py::test_data_result_to_status_dict_matches_api_contract -v
```

Expected: FAIL with import/attribute errors for the new reliability settings/types.

- [ ] **Step 3: Write minimal implementation**

```python
# src/stockpilot/data/errors.py
class CallerDataError(ValueError): ...
class DisabledDataSourceError(RuntimeError): ...
class CoverageEmptyData(LookupError): ...
class SourceResponseError(RuntimeError): ...


# src/stockpilot/data/reliability/types.py
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
    attempted_sources: tuple[dict[str, str], ...] = ()
    cache_state: dict[str, object] | None = None
    retry_after_seconds: int | None = None
    http_status: int = 503

    def to_dict(self) -> dict[str, object]: ...


@dataclass(frozen=True)
class CacheEntry:
    cache_key: str
    domain: str
    market: str
    adapter: str
    request_params_json: str
    subject_key: str | None
    result_kind: str
    status: str
    payload_body: str
    payload_meta_json: str
    fetched_at: datetime
    fresh_until: datetime
    stale_until: datetime


@dataclass(frozen=True)
class SourceHealth:
    adapter: str
    domain: str
    market: str
    state: SourceHealthState
    consecutive_errors: int
    consecutive_successes: int
    last_success_at: datetime | None
    last_failure_at: datetime | None
    cooldown_until: datetime | None
    last_error_type: str | None


@dataclass
class DataResult(Generic[T]):
    status: str
    result_kind: ResultKind
    cache_key: str | None
    source: str | None
    served_from_cache: bool
    fetched_at: datetime | None
    age_seconds: int | None
    degraded_reason: str | None
    missing_symbols: tuple[str, ...]
    attempted_sources: tuple[dict[str, str], ...]
    data: T | None
    error: ReliabilityError | None

    def to_status_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "result_kind": self.result_kind.value,
            "source": self.source,
            "served_from_cache": self.served_from_cache,
            "fetched_at": self.fetched_at.isoformat() if self.fetched_at else None,
            "age_seconds": self.age_seconds,
            "degraded_reason": self.degraded_reason,
            "missing_symbols": list(self.missing_symbols),
            "attempted_sources": list(self.attempted_sources),
        }
```

Also add nested config models in `src/stockpilot/config.py` so `settings.data.reliability` exposes:

1. `enabled`
2. `sqlite_path`
3. `source_order`
4. `cache_windows`
5. `health`

The health config must include `degrade_after_errors`, `cool_down_after_errors`, `cooldown_seconds`, and `recover_after_successes`.

Do not leave reliability config as a raw dict hanging off `yaml_config`; later tasks need typed access.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_reliability_config.py::test_reliability_settings_defaults tests/test_reliability_config.py::test_domain_ids_and_result_kinds_are_canonical tests/test_reliability_config.py::test_data_result_to_status_dict_matches_api_contract -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add config/settings.yaml src/stockpilot/config.py src/stockpilot/data/errors.py src/stockpilot/data/reliability/__init__.py src/stockpilot/data/reliability/types.py tests/test_reliability_config.py
git commit -m "feat: add reliability config and core types" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Add typed adapter classification hooks

**Files:**
- Modify: `src/stockpilot/data/adapters/akshare_adapter.py:44-186`
- Modify: `src/stockpilot/data/adapters/yfinance_adapter.py:35-149`
- Test: `tests/test_reliability_gateway.py`

- [ ] **Step 1: Write the failing test**

```python
def test_yfinance_fundamentals_raise_coverage_empty(monkeypatch):
    class FakeTicker:
        info = {}

    adapter = YFinanceAdapter()
    monkeypatch.setattr("stockpilot.data.adapters.yfinance_adapter.yf.Ticker", lambda symbol: FakeTicker())

    with pytest.raises(CoverageEmptyData):
        adapter.get_fundamental_data("AAPL")


def test_unsupported_market_maps_to_disabled_source():
    adapter = AKShareAdapter()
    with pytest.raises(DisabledDataSourceError):
        adapter.get_stock_list(Market.US)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_reliability_gateway.py::test_yfinance_fundamentals_raise_coverage_empty tests/test_reliability_gateway.py::test_unsupported_market_maps_to_disabled_source -v
```

Expected: FAIL because the adapters currently raise generic errors or return ambiguous empty payloads.

- [ ] **Step 3: Write minimal implementation**

```python
if not info:
    raise CoverageEmptyData(f"No fundamentals coverage for {symbol}")

if market not in self.supported_markets:
    raise DisabledDataSourceError(f"{self.name} does not support {market}")
```

Only add typed exceptions where the adapter can actually distinguish the case. Leave opaque upstream transport failures as generic exceptions so the shield can classify them as `transient_source_error`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_reliability_gateway.py::test_yfinance_fundamentals_raise_coverage_empty tests/test_reliability_gateway.py::test_unsupported_market_maps_to_disabled_source -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stockpilot/data/adapters/akshare_adapter.py src/stockpilot/data/adapters/yfinance_adapter.py tests/test_reliability_gateway.py
git commit -m "feat: add typed reliability adapter errors" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Add the SQLite reliability store

**Files:**
- Create: `src/stockpilot/data/reliability/store.py`
- Test: `tests/test_reliability_store.py`

- [ ] **Step 1: Write the failing test**

```python
def test_store_round_trips_cache_and_health(tmp_path):
    from stockpilot.data.reliability.store import ReliabilityStore

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
    health = store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:01:00Z")

    assert cache_entry.result_kind == "data"
    assert cache_entry.subject_key == "000001"
    assert health.consecutive_errors == 1


def test_begin_probe_is_compare_and_set(tmp_path):
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    assert store.begin_probe("akshare", "price_history", "a_share", "2026-04-17T09:01:00Z") is True
    assert store.begin_probe("akshare", "price_history", "a_share", "2026-04-17T09:01:30Z") is False


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
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_reliability_store.py::test_store_round_trips_cache_and_health tests/test_reliability_store.py::test_begin_probe_is_compare_and_set tests/test_reliability_store.py::test_store_transitions_from_cooling_down_to_recovering_and_healthy tests/test_reliability_store.py::test_store_persists_and_computes_fresh_vs_stale_across_restarts tests/test_reliability_store.py::test_store_fails_open_when_sqlite_access_breaks -v
```

Expected: FAIL because `ReliabilityStore` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class ReliabilityStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._init_schema()

    def get_cache_entry(self, cache_key: str, now: str | None = None) -> CacheEntry | None: ...
    def put_cache_entry(
        self,
        *,
        cache_key: str,
        domain: str,
        market: str,
        request_params_json: str,
        subject_key: str | None,
        payload_format: str,
        payload: dict | list,
        result_kind: str,
        meta: dict[str, object],
        fetched_at: str,
        fresh_until: str,
        stale_until: str,
        adapter: str,
    ) -> None: ...
    def get_source_health(...): ...
    def record_source_success(...): ...
    def record_source_failure(...): ...
    def begin_probe(...): ...
```

Use `sqlite3` from the standard library, keep schema local to this file, and cover all of the spec's store responsibilities:

1. cache round-trip
2. computed fresh/stale windows
3. health state transitions and recovery
4. probe compare-and-set
5. fail-open/stateless behavior

Do not leave these as "later" comments in the file.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_reliability_store.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stockpilot/data/reliability/store.py tests/test_reliability_store.py
git commit -m "feat: add sqlite reliability store" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Add the source registry, shield, gateway, and shared runtime builders

**Files:**
- Create: `src/stockpilot/data/reliability/registry.py`
- Create: `src/stockpilot/data/reliability/shield.py`
- Create: `src/stockpilot/data/reliability/gateway.py`
- Create: `src/stockpilot/data/runtime.py`
- Modify: `src/stockpilot/data/__init__.py`
- Test: `tests/test_reliability_gateway.py`

- [ ] **Step 1: Write the failing test**

```python
class _PriceSuccessAdapter(BaseDataAdapter):
    def __init__(self, name, market):
        self.name = name
        self.supported_markets = [market]

    def get_stock_list(self, market=Market.A_SHARE): return pd.DataFrame()
    def get_price_history(self, symbol, start_date=None, end_date=None, timeframe=None, adjust="qfq"):
        return pd.DataFrame([{"date": "2026-04-17", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}])
    def get_realtime_quote(self, symbol): return {"symbol": symbol, "price": 10.5}
    def get_realtime_quotes(self, symbols): return pd.DataFrame([{"symbol": symbols[0], "price": 10.5}])


class BrokenStore:
    def __init__(self, *args, **kwargs):
        raise sqlite3.OperationalError("db unavailable")


def gateway_with_successful_price_adapter(tmp_path):
    manager = DataManager()
    manager.register_adapter(_PriceSuccessAdapter("akshare", Market.A_SHARE), priority=True)
    return DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"price_history": {"a_share": ["akshare"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )


def gateway_with_partial_quote_adapter(tmp_path):
    manager = DataManager()
    manager.register_adapter(_PriceSuccessAdapter("yfinance", Market.US), priority=True)
    return DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"realtime_quotes": {"us": ["yfinance"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )


def gateway_with_empty_price_history_and_stale_cache(tmp_path):
    class EmptyPriceAdapter(_PriceSuccessAdapter):
        def get_price_history(self, symbol, start_date=None, end_date=None, timeframe=None, adjust="qfq"):
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

    manager = DataManager()
    manager.register_adapter(EmptyPriceAdapter("akshare", Market.A_SHARE), priority=True)
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    store.put_cache_entry(
        cache_key="stale-price",
        domain="price_history",
        market="a_share",
        request_params_json='{"adapter_name":"auto","domain":"price_history","market":"a_share","symbol":"000001"}',
        subject_key="000001",
        payload_format="json",
        payload=[{"date": "2026-04-16", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}],
        result_kind="data",
        meta={"missing_symbols": []},
        fetched_at="2026-04-17T09:00:00Z",
        fresh_until="2026-04-17T09:05:00Z",
        stale_until="2026-04-17T09:30:00Z",
        adapter="akshare",
    )
    return DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"price_history": {"a_share": ["akshare"]}}),
            store=store,
        )
    )


def gateway_with_empty_quote(tmp_path):
    class EmptyQuoteAdapter(_PriceSuccessAdapter):
        def get_realtime_quote(self, symbol): return {}

    manager = DataManager()
    manager.register_adapter(EmptyQuoteAdapter("yfinance", Market.US), priority=True)
    return DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"realtime_quote": {"us": ["yfinance"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )


def gateway_with_empty_search(tmp_path):
    class EmptySearchAdapter(_PriceSuccessAdapter):
        def search(self, keyword): return []

    manager = DataManager()
    manager.register_adapter(EmptySearchAdapter("yfinance", Market.US), priority=True)
    return DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"search": {"us": ["yfinance"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )


def gateway_with_empty_stock_list(tmp_path):
    class EmptyStockListAdapter(_PriceSuccessAdapter):
        def get_stock_list(self, market=Market.US): return pd.DataFrame()

    manager = DataManager()
    manager.register_adapter(EmptyStockListAdapter("yfinance", Market.US), priority=True)
    return DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"stock_list": {"us": ["yfinance"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )


def gateway_with_cooling_down_source(tmp_path):
    gateway = gateway_with_successful_price_adapter(tmp_path)
    gateway.shield.store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:00:00Z")
    gateway.shield.store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:01:00Z")
    gateway.shield.store.record_source_failure("akshare", "price_history", "a_share", "transient_source_error", "2026-04-17T09:02:00Z")
    return gateway


def test_gateway_returns_stale_when_live_fetch_fails_but_cache_is_valid(tmp_path):
    class FailingPriceAdapter(BaseDataAdapter):
        name = "akshare"
        supported_markets = [Market.A_SHARE]

        def get_stock_list(self, market=Market.A_SHARE): return pd.DataFrame()
        def get_price_history(self, symbol, start_date=None, end_date=None, timeframe=None, adjust="qfq"): raise ConnectionError("down")
        def get_realtime_quote(self, symbol): return {}
        def get_realtime_quotes(self, symbols): return pd.DataFrame()

    manager = DataManager()
    manager.register_adapter(FailingPriceAdapter(), priority=True)
    store = ReliabilityStore(tmp_path / "reliability.sqlite3")
    request = DomainRequest(
        domain=DomainId.PRICE_HISTORY,
        market=Market.A_SHARE.value,
        symbol="000001",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 17),
        cache_class=CacheClass.HISTORICAL_SERIES,
    )
    store.put_cache_entry(
        cache_key=make_cache_key(request),
        domain="price_history",
        market="a_share",
        request_params_json='{"adapter_name":"auto","domain":"price_history","end_date":"2026-04-17","market":"a_share","start_date":"2026-01-01","symbol":"000001"}',
        subject_key="000001",
        payload_format="json",
        payload=[{"date": "2026-04-16", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100}],
        result_kind="data",
        meta={"missing_symbols": []},
        fetched_at="2026-04-17T09:00:00Z",
        fresh_until="2026-04-17T09:05:00Z",
        stale_until="2026-04-17T09:30:00Z",
        adapter="akshare",
    )
    gateway = DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"price_history": {"a_share": ["akshare"]}}),
            store=store,
        )
    )

    result = gateway.get_price_history(
        symbol="000001",
        market=Market.A_SHARE,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 17),
    )
    assert result.status == "stale"
    assert result.source == "cache:akshare"


def test_gateway_rejects_non_configured_adapter_override(tmp_path):
    manager = DataManager()
    manager.register_adapter(_PriceSuccessAdapter("akshare", Market.A_SHARE), priority=True)
    manager.register_adapter(_PriceSuccessAdapter("yfinance", Market.US))
    gateway = DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"price_history": {"a_share": ["akshare"], "us": ["yfinance"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )
    error = gateway.get_price_history(
        symbol="000001",
        market=Market.A_SHARE,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 17),
        adapter_name="yfinance",
    ).error
    assert error.code == "DATA_REQUEST_INVALID"


def test_gateway_builds_normalized_unavailable_error(tmp_path):
    manager = DataManager()
    manager.register_adapter(FailingPriceAdapter(), priority=True)
    gateway = DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"price_history": {"a_share": ["akshare"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )
    result = gateway.get_price_history(
        symbol="000001",
        market=Market.A_SHARE,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 17),
    )
    assert result.error.code == "DATA_SOURCE_UNAVAILABLE"
    assert result.error.domain == "price_history"


def test_gateway_marks_batch_as_dataset_incomplete_when_require_complete_is_true(tmp_path):
    gateway = gateway_with_partial_quote_adapter(tmp_path)
    result = gateway.get_realtime_quotes(
        symbols=["AAPL", "MSFT"],
        market=Market.US,
        require_complete=True,
    )
    assert result.error.code == "DATASET_INCOMPLETE"


def test_gateway_uses_adapter_name_in_cache_key(tmp_path):
    gateway = gateway_with_successful_price_adapter(tmp_path)
    auto_result = gateway.get_price_history("000001", market=Market.A_SHARE)
    pinned_result = gateway.get_price_history("000001", market=Market.A_SHARE, adapter_name="akshare")
    assert auto_result.cache_key != pinned_result.cache_key


def test_gateway_respects_registry_market_policy_before_adapter_capability(tmp_path):
    manager = DataManager()
    manager.register_adapter(_PriceSuccessAdapter("akshare", Market.A_SHARE), priority=True)
    manager.register_adapter(_PriceSuccessAdapter("yfinance", Market.A_SHARE))
    gateway = DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"price_history": {"a_share": ["akshare"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )
    result = gateway.get_price_history("000001", market=Market.A_SHARE)
    assert result.source == "akshare"


def test_gateway_classifies_today_request_as_session_series(tmp_path):
    gateway = gateway_with_successful_price_adapter(tmp_path)
    request = gateway.build_price_history_request("000001", Market.A_SHARE, start_date=date.today() - timedelta(days=10), end_date=date.today())
    assert request.cache_class == CacheClass.SESSION_SERIES


def test_gateway_classifies_after_hours_and_weekend_requests_as_historical_series(tmp_path):
    gateway = gateway_with_successful_price_adapter(tmp_path)
    after_hours = gateway.build_price_history_request("000001", Market.A_SHARE, start_date=date.today() - timedelta(days=10), end_date=date.today(), now_override="2026-04-17T18:00:00+08:00")
    weekend = gateway.build_price_history_request("000001", Market.A_SHARE, start_date=date(2026, 4, 10), end_date=date(2026, 4, 11), now_override="2026-04-11T10:00:00+08:00")
    assert after_hours.cache_class == CacheClass.HISTORICAL_SERIES
    assert weekend.cache_class == CacheClass.HISTORICAL_SERIES


def test_gateway_time_zone_failure_falls_back_to_historical_series(monkeypatch, tmp_path):
    gateway = gateway_with_successful_price_adapter(tmp_path)
    monkeypatch.setattr(gateway.shield, "_market_now", lambda market, now_override=None: (_ for _ in ()).throw(ValueError("tz failed")))
    request = gateway.build_price_history_request("000001", Market.A_SHARE, start_date=date.today() - timedelta(days=10), end_date=date.today())
    assert request.cache_class == CacheClass.HISTORICAL_SERIES


def test_price_history_all_empty_does_not_substitute_stale_cache(tmp_path):
    gateway = gateway_with_empty_price_history_and_stale_cache(tmp_path)
    result = gateway.get_price_history("000001", market=Market.A_SHARE)
    assert result.status == "fresh"
    assert result.result_kind == ResultKind.EMPTY


def test_realtime_quote_empty_is_invalid(tmp_path):
    gateway = gateway_with_empty_quote(tmp_path)
    result = gateway.get_realtime_quote("AAPL", market=Market.US)
    assert result.error.code == "DATA_SOURCE_UNAVAILABLE"


def test_search_empty_is_valid(tmp_path):
    gateway = gateway_with_empty_search(tmp_path)
    result = gateway.search("zzzz", market=Market.US)
    assert result.status == "fresh"
    assert result.result_kind == ResultKind.EMPTY


def test_fundamentals_coverage_empty_maps_to_fresh_empty(tmp_path):
    class EmptyFundamentalsAdapter(_PriceSuccessAdapter):
        def get_fundamental_data(self, symbol):
            raise CoverageEmptyData(f"No fundamentals coverage for {symbol}")

    manager = DataManager()
    manager.register_adapter(EmptyFundamentalsAdapter("yfinance", Market.US), priority=True)
    gateway = DataGateway(
        shield=ReliabilityShield(
            data_manager=manager,
            registry=SourceRegistry({"fundamental_data": {"us": ["yfinance"]}}),
            store=ReliabilityStore(tmp_path / "reliability.sqlite3"),
        )
    )
    result = gateway.get_fundamental_data("AAPL", market=Market.US)
    assert result.status == "fresh"
    assert result.result_kind == ResultKind.EMPTY


def test_stock_list_empty_is_invalid(tmp_path):
    gateway = gateway_with_empty_stock_list(tmp_path)
    result = gateway.get_stock_list(market=Market.US)
    assert result.error.code == "DATA_SOURCE_UNAVAILABLE"


def test_gateway_stays_unavailable_while_source_is_cooling_down(tmp_path):
    gateway = gateway_with_cooling_down_source(tmp_path)
    result = gateway.get_price_history("000001", market=Market.A_SHARE)
    assert result.error.code == "DATA_SOURCE_UNAVAILABLE"


def test_build_default_data_gateway_falls_back_to_stateless_store(monkeypatch):
    monkeypatch.setattr("stockpilot.data.reliability.store.ReliabilityStore", BrokenStore)
    gateway = build_default_data_gateway()
    assert gateway.shield.store.stateless is True
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_reliability_gateway.py -v
```

Expected: FAIL because the gateway/registry/runtime layer does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# src/stockpilot/data/reliability/shield.py
class ReliabilityShield:
    def execute(
        self,
        request: DomainRequest,
        fetch_live: Callable[[BaseDataAdapter, DomainRequest], pd.DataFrame | dict | list],
    ) -> DataResult[pd.DataFrame | dict | list]:
        cache_key = make_cache_key(request)
        cache_entry = self.store.get_cache_entry(cache_key)
        ...


# src/stockpilot/data/reliability/gateway.py
class DataGateway:
    def get_price_history(...): return self._run(DomainId.PRICE_HISTORY, ...)
    def get_realtime_quote(...): return self._run(DomainId.REALTIME_QUOTE, ...)
    def get_realtime_quotes(...): return self._run(DomainId.REALTIME_QUOTES, ...)
    def get_fundamental_data(...): return self._run(DomainId.FUNDAMENTAL_DATA, ...)
    def get_stock_list(...): return self._run(DomainId.STOCK_LIST, ...)
    def search(...): return self._run(DomainId.SEARCH, ...)
```

Keep `SourceRegistry` static and phase-1-only. Put these in the new reliability package, not in `api/main.py`:

1. canonical cache-key normalization
2. session-vs-historical cache class selection
3. normalized error envelopes
4. `require_complete` handling for batch quote requests
5. default runtime builders
6. domain rules for `price_history`, `realtime_quote`, `realtime_quotes`, `stock_list`, and `search`
7. typed exception mapping for `caller_error`, `disabled_source`, `coverage_empty`, and `source_response_error`

Do not bury `ReliabilityShield` inside `DataGateway`; keep them as separate classes even if they live in the same package.
Write one small helper factory module for test doubles in `tests/test_reliability_gateway.py` instead of hiding setup in undefined fixtures.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_reliability_config.py tests/test_reliability_store.py tests/test_reliability_gateway.py -v
```

Expected: PASS for the new config/store/gateway tests.

- [ ] **Step 5: Commit**

```bash
git add src/stockpilot/data/__init__.py src/stockpilot/data/reliability/registry.py src/stockpilot/data/reliability/shield.py src/stockpilot/data/reliability/gateway.py src/stockpilot/data/runtime.py tests/test_reliability_gateway.py
git commit -m "feat: add reliability gateway and shield" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Chunk 2: API integration

### Task 5: Wire single-resource API routes to the gateway

**Files:**
- Modify: `src/stockpilot/api/main.py:124-515`
- Modify: `src/stockpilot/web/static/js/app.js:6-16`
- Modify: `src/stockpilot/web/static/js/analysis.js:96-136`
- Create: `tests/reliability_fakes.py`
- Create: `tests/test_api_reliability.py`
- Modify: `tests/test_api_v2.py:28-177`
- Modify: `tests/test_smoke.py:359-399`

- [ ] **Step 1: Write the failing test**

```python
from tests.reliability_fakes import (
    gateway_with_empty_result,
    gateway_with_invalid_request,
    gateway_with_stale_single_result,
    gateway_with_unavailable_single_result,
)


def test_price_route_includes_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_stale_single_result(domain="price_history", source="cache:yfinance"), raising=False)
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/price?market=us")

    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"
    assert response.json()["data_status"]["result_kind"] == "data"
    assert response.json()["data_status"]["served_from_cache"] is True
    assert response.json()["data_status"]["source"] == "cache:yfinance"
    assert response.json()["data_status"]["fetched_at"] == "2026-04-17T09:25:00Z"
    assert response.json()["data_status"]["age_seconds"] == 600
    assert response.json()["data_status"]["degraded_reason"] == "live sources unavailable; serving cached payload"
    assert response.json()["data_status"]["missing_symbols"] == []
    assert response.json()["data_status"]["attempted_sources"][0]["adapter"] == "yfinance"
    assert response.json()["data_status"]["attempted_sources"][0]["outcome"] == "error"


def test_chart_data_includes_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_stale_single_result(domain="price_history", source="cache:yfinance"), raising=False)
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/chart-data?days=30&market=us")

    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"
    assert response.json()["data_status"]["source"] == "cache:yfinance"


def test_fundamentals_route_includes_data_status_on_success(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_stale_single_result(domain="fundamental_data", source="cache:yfinance"), raising=False)
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/fundamentals?market=us")
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_fundamentals_route_maps_empty_to_404(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_empty_result(domain="fundamental_data"), raising=False)
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/UNKNOWN/fundamentals?market=us")
    assert response.status_code == 404
    assert response.json()["detail"]["status"] == "not_found"
    assert response.json()["detail"]["code"] == "DATA_NOT_FOUND"
    assert response.json()["detail"]["domain"] == "fundamental_data"
    assert response.json()["detail"]["market"] == "us"


def test_fundamentals_route_preserves_invalid_request(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_invalid_request(domain="fundamental_data"), raising=False)
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/fundamentals?market=us")
    assert response.status_code == 400
    assert response.json()["detail"]["status"] == "invalid_request"
    assert response.json()["detail"]["code"] == "DATA_REQUEST_INVALID"
    assert response.json()["detail"]["domain"] == "fundamental_data"


def test_technical_analysis_route_includes_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_stale_single_result(domain="price_history", source="cache:yfinance"), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/analysis/technical", json={"symbol": "AAPL", "market": "us"})
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_patterns_route_includes_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_stale_single_result(domain="price_history", source="cache:yfinance"), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/analysis/patterns", json={"symbol": "AAPL", "market": "us"})
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_patterns_route_maps_data_not_found_to_404(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_empty_result(domain="price_history"), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/analysis/patterns", json={"symbol": "UNKNOWN", "market": "us"})
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "DATA_NOT_FOUND"


def test_chart_data_maps_unavailable_to_503(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_unavailable_single_result(domain="price_history"), raising=False)
    client = TestClient(api_main.app)

    response = client.get("/api/v1/stocks/AAPL/chart-data?days=30&market=us")
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "unavailable"
    assert response.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert response.json()["detail"]["domain"] == "price_history"
    assert response.json()["detail"]["symbol"] == "AAPL"
    assert response.json()["detail"]["market"] == "us"
    assert response.json()["detail"]["retry_after_seconds"] == 120
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_api_reliability.py::test_price_route_includes_data_status tests/test_api_reliability.py::test_chart_data_includes_data_status tests/test_api_reliability.py::test_chart_data_maps_unavailable_to_503 tests/test_api_reliability.py::test_fundamentals_route_includes_data_status_on_success tests/test_api_reliability.py::test_fundamentals_route_maps_empty_to_404 tests/test_api_reliability.py::test_fundamentals_route_preserves_invalid_request tests/test_api_reliability.py::test_technical_analysis_route_includes_data_status tests/test_api_reliability.py::test_patterns_route_includes_data_status tests/test_api_reliability.py::test_patterns_route_maps_data_not_found_to_404 -v
```

Expected: FAIL because API routes still use `_build_data_manager()` and return raw payloads without `data_status`.

- [ ] **Step 3: Write minimal implementation**

Add the shared API-test fakes in `tests/reliability_fakes.py`:

```python
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


class FakeGateway:
    """Tiny gateway fake used only by API/CLI contract tests."""

    def __init__(self, *, single_result=None, per_symbol=None):
        self.single_result = single_result
        self.per_symbol = per_symbol or {}

    @classmethod
    def single(cls, *, domain: str, status: str, result_kind: str, source: str, served_from_cache: bool = False, age_seconds: int | None = None):
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
                        "outcome": "error" if status == "stale" else ("empty" if result_kind == "empty" else "success"),
                    }
                ],
            )
        )

    @classmethod
    def error(cls, *, domain: str, status: str, code: str, http_status: int):
        return cls(single_result=build_error_result(domain=domain, status=status, code=code, http_status=http_status))

    @classmethod
    def multi(cls, *, status: str | None = None, source: str | None = None, result_kind: str = "data", served_from_cache: bool = False, empty_symbols: list[str] | None = None, unavailable_symbols: list[str] | None = None):
        empty = set(empty_symbols or [])
        unavailable = set(unavailable_symbols or [])
        per_symbol = {}
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
                attempted_sources=[
                    {
                        "symbol": symbol,
                        "adapter": "akshare",
                        "outcome": "empty" if symbol in empty else "success",
                    }
                ],
            )
        return cls(per_symbol=per_symbol)

    def get_price_history(self, symbol, **kwargs):
        return self.per_symbol.get(symbol, self.single_result)

    def get_fundamental_data(self, symbol, **kwargs):
        return self.single_result


class RecordingGateway:
    """Returns one canned result for any symbol and records request args for api_v2 tests."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def get_price_history(self, symbol, **kwargs):
        self.calls.append({"symbol": symbol, **kwargs})
        return self.result


def gateway_with_stale_single_result(*, domain: str, source: str):
    return FakeGateway.single(domain=domain, status="stale", result_kind="data", source=source, served_from_cache=True, age_seconds=600)


def gateway_with_empty_result(*, domain: str):
    return FakeGateway.single(domain=domain, status="fresh", result_kind="empty", source="yfinance")


def gateway_with_invalid_request(*, domain: str):
    return FakeGateway.error(domain=domain, status="invalid_request", code="DATA_REQUEST_INVALID", http_status=400)


def gateway_with_invalid_required_symbol():
    return FakeGateway(
        per_symbol={
            "AAA": build_result(
                domain="price_history",
                status="fresh",
                result_kind="data",
                source="yfinance",
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


def gateway_with_partial_required_symbol():
    return FakeGateway(
        per_symbol={
            "AAA": build_result(
                domain="price_history",
                status="fresh",
                result_kind="partial",
                source="yfinance",
                missing_symbols=["BBB"],
                attempted_sources=[{"adapter": "yfinance", "outcome": "partial"}],
            ),
            "BBB": build_result(
                domain="price_history",
                status="fresh",
                result_kind="data",
                source="yfinance",
                attempted_sources=[{"adapter": "yfinance", "outcome": "success"}],
            ),
        }
    )


def gateway_with_unavailable_required_symbol():
    return FakeGateway.multi(status="fresh", source="yfinance", unavailable_symbols=["BBB"])


def gateway_with_unavailable_single_result(*, domain: str):
    return FakeGateway.error(domain=domain, status="unavailable", code="DATA_SOURCE_UNAVAILABLE", http_status=503)


def gateway_with_empty_required_symbol():
    return FakeGateway.multi(status="fresh", source="yfinance", empty_symbols=["BBB"])


def gateway_with_compare_results():
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
                attempted_sources=[{"adapter": "yfinance", "outcome": "success"}],
            ),
            "BBB": build_result(
                domain="price_history",
                status="stale",
                result_kind="data",
                source="cache:akshare",
                served_from_cache=True,
                age_seconds=600,
                fetched_at="2026-04-17T09:25:00Z",
                degraded_reason="live sources unavailable; serving cached payload",
                attempted_sources=[{"adapter": "akshare", "outcome": "error", "reason": "ConnectionError"}],
            ),
        }
    )
```

`build_result(...)` / `build_error_result(...)` should be tiny local helpers that wrap the new `DataResult` and `ReliabilityError` dataclasses so the tests stay readable. `build_result(...)` should pick `sample_price_history(symbol)` for `price_history` and `sample_fundamental_data(symbol)` for `fundamental_data`, so chart/analysis/backtest code sees realistic payloads instead of `None`. Give `build_result(...)` deterministic defaults for API assertions: `fetched_at="2026-04-17T09:25:00Z"`, `missing_symbols=[]`, and `degraded_reason="live sources unavailable; serving cached payload"` whenever `status == "stale"`; otherwise `degraded_reason=None`. Give `build_error_result(...)` deterministic retry guidance for 503 cases with `retry_after_seconds=120`.

Keep the fake intentionally tiny: only implement the real gateway methods the route and CLI tests call (`get_price_history(...)` and `get_fundamental_data(...)`). `FakeGateway.multi(...)` must return one `DataResult` per requested symbol so `aggregate_route_status(...)` can flatten the symbol-tagged `attempted_sources` entries asserted in Task 6.

Then add the production helper in `src/stockpilot/api/main.py`:

```python
def _build_data_gateway():
    from stockpilot.data.runtime import build_default_data_gateway
    return build_default_data_gateway()


def _status_dict(result):
    return result.to_status_dict()
```

Replace the single-resource route helper with a gateway-backed helper that:

1. calls the gateway
2. preserves `invalid_request` as HTTP 400
3. translates successful single-resource `result_kind="empty"` payloads into HTTP 404 `DATA_NOT_FOUND`
4. maps `unavailable` to HTTP 503
5. attaches `data_status` on success
6. when raising a gateway-managed error, always use `HTTPException(status_code=result.error.http_status, detail=result.error.to_dict())`; do the same after translating `result_kind="empty"` into a normalized `not_found` envelope

Also update the existing `tests/test_api_v2.py` monkeypatches that currently replace `_build_data_manager()`:

1. `test_chart_data_returns_indicator_scores`
2. `test_patterns_route_uses_requested_market`
3. `test_patterns_route_serializes_numpy_pattern_strength`

Those three tests should monkeypatch `_build_data_gateway()` with `gateway_with_stale_single_result(...)`, because those routes no longer read through `_build_data_manager()`.

For the market-propagation assertions in `tests/test_api_v2.py`, use `RecordingGateway(gateway_with_stale_single_result(...).single_result)` so the tests can still verify `gateway.calls[0]["market"] == Market.US` (and any existing symbol/start/end assertions) after the route wiring changes.

Update `src/stockpilot/web/static/js/app.js` so the shared `api()` helper becomes reliability-aware:

1. add `formatApiError(detail)` so page modules can render `detail.message`, `detail.code`, and `retry_after_seconds` consistently
2. add `consumeDataStatus(payload, { dedupeKey })` so page modules can surface one stale-data warning per action instead of one toast per fetch
3. when `res.ok` is false and `err.detail` is an object, throw `Error(formatApiError(err.detail))` and attach `error.detail = err.detail`
4. make `consumeDataStatus(...)` a safe no-op when `payload.data_status` is missing so Task 5 stays atomic even before Task 6 wires compare/portfolio responses
5. leave the returned JSON shape unchanged so existing page modules keep working

Then update `analysis.js` to call `formatApiError(e.detail || { message: e.message })` and pass a stable `dedupeKey` into `consumeDataStatus(...)` after successful API calls.

Render the degraded/error state inline in the existing page panels instead of toast-only:

1. `analysis.js`: prepend a small amber notice card inside `#analysis-signal` when either chart-data or patterns returns `data_status.status === "stale"`; on failure keep using `#analysis-chart` / `#analysis-patterns`, but populate them with `formatApiError(...)` output so retry guidance is visible in-page
2. compare/portfolio page rendering moves to Task 6, alongside the routes that first expose multi-load `data_status`

Extend `tests/test_smoke.py::test_web_dashboard` to assert the served `/static/js/app.js` bundle now contains `formatApiError`, `consumeDataStatus`, `retry_after_seconds`, and the dedupe-key logic, and fetch `/static/js/analysis.js` to assert it references `formatApiError(` or `consumeDataStatus(`. Because the repo has no browser-side JS test harness, this static-contract smoke check plus the API contract tests are the verification boundary for the analysis-page wiring in this chunk.

Apply that helper to the phase-1 single-resource routes in `api/main.py`:

1. `GET /api/v1/stocks/{symbol}/price`
2. `GET /api/v1/stocks/{symbol}/fundamentals`
3. `POST /api/v1/analysis/technical`
4. `POST /api/v1/analysis/patterns`
5. `GET /api/v1/stocks/{symbol}/chart-data`

Keep the route payload shapes stable other than the new `data_status` sibling field.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_api_reliability.py tests/test_api_v2.py tests/test_smoke.py -v
```

Expected: PASS.

Manual browser smoke (required because there is no JS execution test harness; same worktree, do not commit the temporary override):

```bash
python -m stockpilot.cli serve
```

Setup: temporarily point `_build_data_gateway()` in `src/stockpilot/api/main.py` at `gateway_with_stale_single_result(domain="price_history", source="cache:yfinance")` for the stale case and `gateway_with_unavailable_single_result(domain="price_history")` for the error case.

Expected in the browser after loading `/` and exercising the analysis page once under each temporary override:

1. stale analysis responses show one inline amber notice card, not a stack of duplicate toasts
2. error responses keep the page intact and render retry guidance from `retry_after_seconds`
3. no uncaught exception appears in the browser console

- [ ] **Step 5: Commit**

```bash
git add src/stockpilot/api/main.py src/stockpilot/web/static/js/app.js src/stockpilot/web/static/js/analysis.js tests/reliability_fakes.py tests/test_api_reliability.py tests/test_api_v2.py tests/test_smoke.py
git commit -m "feat: add reliability status to single-resource api routes" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Wire multi-load API routes and route-level aggregation

**Files:**
- Modify: `src/stockpilot/api/main.py:381-610`
- Modify: `src/stockpilot/data/reliability/gateway.py`
- Modify: `src/stockpilot/web/static/js/compare.js:16-73`
- Modify: `src/stockpilot/web/static/js/portfolio.js:24-74`
- Modify: `tests/reliability_fakes.py`
- Modify: `tests/test_reliability_gateway.py`
- Test: `tests/test_api_reliability.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
from tests.reliability_fakes import (
    gateway_with_compare_results,
    gateway_with_empty_required_symbol,
    gateway_with_invalid_required_symbol,
    gateway_with_partial_required_symbol,
    gateway_with_unavailable_required_symbol,
)


def test_compare_route_aggregates_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_compare_results(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/compare/symbols", json={"symbols": ["AAA", "BBB"], "market": "us", "days": 60})

    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"
    assert response.json()["data_status"]["source"] == "mixed"
    assert response.json()["data_status"]["result_kind"] == "data"
    assert response.json()["data_status"]["served_from_cache"] is True
    assert response.json()["data_status"]["fetched_at"] == "2026-04-17T09:25:00Z"
    assert response.json()["data_status"]["age_seconds"] == 600
    assert response.json()["data_status"]["degraded_reason"] == "live sources unavailable; serving cached payload"
    assert response.json()["data_status"]["missing_symbols"] == []
    assert response.json()["data_status"]["attempted_sources"] == [
        {"symbol": "AAA", "adapter": "yfinance", "outcome": "success"},
        {"symbol": "BBB", "adapter": "akshare", "outcome": "error", "reason": "ConnectionError"},
    ]


def test_portfolio_route_returns_503_when_required_symbol_is_unavailable(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_unavailable_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/portfolio/optimize", json={"symbols": ["AAA", "BBB"], "market": "us"})
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "unavailable"
    assert response.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert response.json()["detail"]["symbol"] == "BBB"
    assert response.json()["detail"]["retry_after_seconds"] == 120


def test_compare_route_returns_404_when_required_symbol_is_empty(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_empty_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/compare/symbols", json={"symbols": ["AAA", "BBB"], "market": "us", "days": 60})
    assert response.status_code == 404
    assert response.json()["detail"]["status"] == "not_found"
    assert response.json()["detail"]["code"] == "DATA_NOT_FOUND"
    assert response.json()["detail"]["symbol"] == "BBB"


def test_compare_route_preserves_invalid_request(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_invalid_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/compare/symbols", json={"symbols": ["AAA", "BBB"], "market": "us", "days": 60})
    assert response.status_code == 400
    assert response.json()["detail"]["status"] == "invalid_request"
    assert response.json()["detail"]["code"] == "DATA_REQUEST_INVALID"


def test_compare_route_returns_503_when_required_result_is_partial(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_partial_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/compare/symbols", json={"symbols": ["AAA", "BBB"], "market": "us", "days": 60})
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "dataset_incomplete"
    assert response.json()["detail"]["code"] == "DATASET_INCOMPLETE"
    assert response.json()["detail"]["missing_symbols"] == ["BBB"]


def test_backtest_compare_returns_503_when_required_symbol_is_unavailable(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_unavailable_required_symbol(), raising=False)
    client = TestClient(api_main.app)

    response = client.post(
        "/api/v1/backtest/compare",
        json={
            "runs": [
                {"symbol": "AAA", "strategy": "ma_crossover", "market": "us"},
                {"symbol": "BBB", "strategy": "ma_crossover", "market": "us"},
            ],
            "days": 120,
            "initial_capital": 100000,
        },
    )
    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "unavailable"
    assert response.json()["detail"]["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert response.json()["detail"]["symbol"] == "BBB"
    assert response.json()["detail"]["retry_after_seconds"] == 120


def test_portfolio_route_success_includes_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_compare_results(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/portfolio/optimize", json={"symbols": ["AAA", "BBB"], "market": "us"})
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"


def test_backtest_compare_success_includes_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_compare_results(), raising=False)
    client = TestClient(api_main.app)

    response = client.post(
        "/api/v1/backtest/compare",
        json={
            "runs": [
                {"symbol": "AAA", "strategy": "ma_crossover", "market": "us"},
                {"symbol": "BBB", "strategy": "ma_crossover", "market": "us"},
            ],
            "days": 120,
            "initial_capital": 100000,
        },
    )
    assert response.status_code == 200
    assert response.json()["data_status"]["status"] == "stale"
```

Also add direct gateway-unit coverage in `tests/test_reliability_gateway.py`:

```python
def test_aggregate_route_status_keeps_fresh_single_source_when_all_inputs_are_fresh():
    status = aggregate_route_status([("AAA", fresh_result(source="yfinance")), ("BBB", fresh_result(source="yfinance"))])
    assert status.status == "fresh"
    assert status.source == "yfinance"
    assert status.age_seconds == 0


def test_aggregate_route_status_uses_mixed_source_and_stale_metadata():
    status = aggregate_route_status([("AAA", fresh_result(source="yfinance")), ("BBB", stale_result(source="cache:akshare", age_seconds=600))])
    assert status.status == "stale"
    assert status.source == "mixed"
    assert status.fetched_at == "2026-04-17T09:25:00Z"
    assert status.age_seconds == 600


def test_aggregate_route_status_prefers_invalid_request_over_not_found_and_unavailable():
    status = aggregate_route_status([("AAA", invalid_request_result()), ("BBB", empty_result()), ("CCC", unavailable_result())])
    assert status.error.status == "invalid_request"
    assert status.error.http_status == 400


def test_aggregate_route_status_maps_partial_to_dataset_incomplete():
    status = aggregate_route_status([("AAA", partial_result(missing_symbols=["BBB"]))])
    assert status.error.status == "dataset_incomplete"
    assert status.error.code == "DATASET_INCOMPLETE"
    assert status.error.missing_symbols == ["BBB"]
```

Use tiny local constructors in that test file (`fresh_result`, `stale_result`, `invalid_request_result`, `empty_result`, `unavailable_result`, `partial_result`) that wrap the new `DataResult` / `ReliabilityError` dataclasses directly, so the aggregation rules are unit-tested without going through API fakes.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_reliability_gateway.py::test_aggregate_route_status_keeps_fresh_single_source_when_all_inputs_are_fresh tests/test_reliability_gateway.py::test_aggregate_route_status_uses_mixed_source_and_stale_metadata tests/test_reliability_gateway.py::test_aggregate_route_status_prefers_invalid_request_over_not_found_and_unavailable tests/test_reliability_gateway.py::test_aggregate_route_status_maps_partial_to_dataset_incomplete tests/test_api_reliability.py::test_compare_route_aggregates_data_status tests/test_api_reliability.py::test_portfolio_route_returns_503_when_required_symbol_is_unavailable tests/test_api_reliability.py::test_compare_route_returns_404_when_required_symbol_is_empty tests/test_api_reliability.py::test_compare_route_preserves_invalid_request tests/test_api_reliability.py::test_compare_route_returns_503_when_required_result_is_partial tests/test_api_reliability.py::test_backtest_compare_returns_503_when_required_symbol_is_unavailable tests/test_api_reliability.py::test_portfolio_route_success_includes_data_status tests/test_api_reliability.py::test_backtest_compare_success_includes_data_status -v
```

Expected: FAIL because the multi-load routes currently skip errors or silently continue when one required symbol is empty or unavailable.

- [ ] **Step 3: Write minimal implementation**

```python
aggregated_status = aggregate_route_status(per_symbol_results)
if aggregated_status.error is not None:
    raise HTTPException(status_code=aggregated_status.error.http_status, detail=aggregated_status.error.to_dict())
```

Make compare, backtest-compare, and portfolio optimization all follow the spec:

1. required symbol `empty` => 404 `DATA_NOT_FOUND`
2. required symbol `unavailable` => 503 `DATA_SOURCE_UNAVAILABLE`
3. gateway `invalid_request` stays HTTP 400 if a route-level loader receives it
4. successful multi-load response => single top-level `data_status`
5. `aggregate_route_status(...)` lives in `src/stockpilot/data/reliability/gateway.py`, not as another large ad-hoc helper inside `api/main.py`
6. `aggregate_route_status(...)` returns a `DataResult` whose `to_status_dict()` fills the full spec shape: `status`, `result_kind`, `source`, `served_from_cache`, `fetched_at`, `age_seconds`, `degraded_reason`, `missing_symbols`, and `attempted_sources`
7. route handlers should share one `_load_required_price_histories(...)` helper so compare, backtest-compare, and portfolio all inherit the same `unavailable` / `not_found` behavior instead of duplicating loops
8. repeated single-symbol `price_history` loads should not manufacture partial success, but if `aggregate_route_status(...)` ever receives a `result_kind="partial"` input, normalize it to HTTP 503 `DATASET_INCOMPLETE` with `missing_symbols` preserved
9. when mixed failures occur inside one required batch, use deterministic precedence: `invalid_request` (400) first, then `not_found` (404), then `unavailable` (503)
10. `_load_required_price_histories(...)` must key cached/request-local results by `(symbol, market)` and preserve caller order, so repeated symbols reuse the same fetch only within the same market and `backtest/compare` runs with different markets never overwrite each other
11. route-level provenance comes from loader context, not from the single-resource gateway contract: `_load_required_price_histories(...)` should pass `(symbol, result)` pairs into `aggregate_route_status(...)`, and the aggregator should inject that symbol into each flattened `attempted_sources` entry

For aggregated success metadata, keep the rules deterministic:

1. `served_from_cache` is `true` if any required symbol was served from cache
2. `fetched_at` is the oldest non-null `fetched_at` across required symbols
3. `age_seconds` is the maximum non-null age across required symbols
4. `degraded_reason` is the first non-null degraded reason when the aggregated status is `stale`; otherwise `null`
5. `missing_symbols` is always `[]` on successful compare/backtest-compare/portfolio responses because empties fail the route instead of producing partial success

To keep `compare_backtests` aligned with that shared loader, add a pure `_run_backtest_with_df(symbol, strategy, df, start_date, end_date, initial_capital)` helper and have `compare_backtests` call it after `_load_required_price_histories(...)` has already fetched every required symbol. Leave `/api/v1/backtest/run` unchanged in this chunk; it is outside the phase-1 API touchpoints named in the spec.

Also update the existing smoke tests that currently patch `_build_data_manager()` / `_run_backtest_job`:

1. `test_interactive_web_api_routes` should patch `_build_data_gateway` with a `RecordingGateway`-style fake that returns valid price-history data for any requested symbol and patch `_run_backtest_with_df` instead of `_run_backtest_job`
2. `test_compare_symbols_handles_upstream_failures` should patch `_build_data_gateway` with `gateway_with_unavailable_required_symbol()` and assert `detail.status == "unavailable"` plus `detail.code == "DATA_SOURCE_UNAVAILABLE"`
3. `test_backtest_compare_handles_upstream_failures` should do the same for the compare-backtest path and stop asserting legacy string messages

With the multi-load routes now returning `data_status`, update the web consumers in this task:

1. `compare.js`: call `consumeDataStatus(data, { dedupeKey: \`compare:${symbols.join(",")}:${market}:${days}\` })`, prepend an inline stale-warning card to `#compare-cards`, and render `formatApiError(...)` output in both `#compare-chart` and `#compare-cards` on failure
2. `portfolio.js`: call `consumeDataStatus(selected, { dedupeKey: \`portfolio:${symbols.join(",")}:${method}:${market}\` })`, prepend an inline stale-warning card to `#pf-metrics`, and on failure unhide `#pf-results` plus render a retry-guidance card inside `#pf-metrics`
3. extend `tests/test_smoke.py::test_web_dashboard` to fetch `/static/js/compare.js` and `/static/js/portfolio.js` and assert those modules reference `formatApiError(` or `consumeDataStatus(`

Do **not** reintroduce phase-2 behavior such as multi-source live merge or per-item status trees.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_reliability_gateway.py tests/test_api_reliability.py tests/test_api_v2.py tests/test_smoke.py -v
```

Expected: PASS.

Manual browser smoke for the compare/portfolio web UX (same worktree, do not commit the temporary override):

1. temporarily point `_build_data_gateway()` in `src/stockpilot/api/main.py` at `gateway_with_compare_results()` to verify stale inline panels
2. temporarily point it at `gateway_with_unavailable_required_symbol()` to verify formatted retry-guidance errors
3. run `python -m stockpilot.cli serve`
4. load `/`, exercise compare and portfolio once each, then revert the temporary override before committing

- [ ] **Step 5: Commit**

```bash
git add src/stockpilot/api/main.py src/stockpilot/data/reliability/gateway.py src/stockpilot/web/static/js/compare.js src/stockpilot/web/static/js/portfolio.js tests/reliability_fakes.py tests/test_api_reliability.py tests/test_api_v2.py tests/test_smoke.py
git commit -m "feat: add reliability aggregation to multi-load api routes" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 7: Add the realtime quotes watchlist touchpoint

**Files:**
- Modify: `src/stockpilot/data/reliability/gateway.py`
- Modify: `src/stockpilot/api/main.py:124-626`
- Modify: `src/stockpilot/web/static/js/app.js:6-179`
- Modify: `tests/reliability_fakes.py`
- Modify: `tests/test_reliability_gateway.py`
- Test: `tests/test_api_reliability.py`

- [ ] **Step 1: Write the failing test**

```python
from tests.reliability_fakes import (
    gateway_with_realtime_quotes_batch,
    gateway_with_partial_quotes_batch,
    gateway_with_unavailable_quotes_batch,
)


def test_quotes_route_returns_batch_data_status(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_realtime_quotes_batch(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/quotes", json={"symbols": ["AAA", "BBB"], "market": "us"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"]["status"] == "fresh"
    assert payload["data_status"]["result_kind"] == "data"
    assert payload["data_status"]["source"] == "yfinance"
    assert payload["data_status"]["missing_symbols"] == []
    assert payload["quotes"] == [
        {"symbol": "AAA", "price": 101.5, "change_pct": 0.42},
        {"symbol": "BBB", "price": 57.0, "change_pct": -0.11},
    ]


def test_quotes_route_returns_partial_batch(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_partial_quotes_batch(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/quotes", json={"symbols": ["AAA", "BBB"], "market": "us"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_status"]["status"] == "stale"
    assert payload["data_status"]["result_kind"] == "partial"
    assert payload["data_status"]["missing_symbols"] == ["BBB"]
    assert payload["data_status"]["degraded_reason"] == "quote provider returned partial batch"
    assert [q["symbol"] for q in payload["quotes"]] == ["AAA"]


def test_quotes_route_maps_unavailable_to_503(monkeypatch):
    monkeypatch.setattr(api_main, "_build_data_gateway", lambda: gateway_with_unavailable_quotes_batch(), raising=False)
    client = TestClient(api_main.app)

    response = client.post("/api/v1/quotes", json={"symbols": ["AAA", "BBB"], "market": "us"})

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["status"] == "unavailable"
    assert detail["code"] == "DATA_SOURCE_UNAVAILABLE"
    assert detail["domain"] == "realtime_quotes"
    assert detail["market"] == "us"
    assert detail["retry_after_seconds"] == 120
```

Also add a direct gateway-unit test in `tests/test_reliability_gateway.py`:

```python
def test_get_realtime_quotes_returns_batch_result():
    gateway = build_gateway_with_fake_shield(
        quote_results={"AAA": fresh_quote_result({"price": 101.5}), "BBB": fresh_quote_result({"price": 57.0})}
    )
    result = gateway.get_realtime_quotes(symbols=["AAA", "BBB"], market="us")
    assert result.status == "fresh"
    assert result.result_kind == "data"
    assert [q["symbol"] for q in result.data] == ["AAA", "BBB"]
    assert result.missing_symbols == []


def test_get_realtime_quotes_flags_partial_batch():
    gateway = build_gateway_with_fake_shield(
        quote_results={"AAA": fresh_quote_result({"price": 101.5}), "BBB": empty_quote_result()}
    )
    result = gateway.get_realtime_quotes(symbols=["AAA", "BBB"], market="us")
    assert result.status == "stale"
    assert result.result_kind == "partial"
    assert result.missing_symbols == ["BBB"]
    assert result.degraded_reason == "quote provider returned partial batch"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_api_reliability.py::test_quotes_route_returns_batch_data_status tests/test_reliability_gateway.py::test_get_realtime_quotes_returns_batch_result -v
```

Expected: FAIL because `/api/v1/quotes` does not exist, `gateway.get_realtime_quotes(...)` is not implemented, and the new fakes are missing.

- [ ] **Step 3: Write minimal implementation**

Add the new fakes to `tests/reliability_fakes.py` (`gateway_with_realtime_quotes_batch`, `gateway_with_partial_quotes_batch`, `gateway_with_unavailable_quotes_batch`). Use the canonical defaults locked in during Chunk 2: fresh `fetched_at="2026-04-17T09:35:00Z"`, stale `fetched_at="2026-04-17T09:25:00Z"` with `age_seconds=600`, and 503 fakes emitting `retry_after_seconds=120`.

Add `DataGateway.get_realtime_quotes(symbols: list[str], market: str) -> DataResult` in `src/stockpilot/data/reliability/gateway.py`:

- per-symbol calls go through the existing shield using cache class `live_quote` (spec line 268) and domain `realtime_quotes`
- aggregate the per-symbol shield results into one `DataResult`:
  - all-success → `status="fresh"`, `result_kind="data"`, ordered `data=[quotes...]`, `missing_symbols=[]`
  - some-success → `result_kind="partial"`, `status="stale"`, `degraded_reason="quote provider returned partial batch"`, `missing_symbols=[<in caller order>]`
  - all-fail → reuse existing `aggregate_route_status(...)` precedence so invalid/not-found/unavailable envelopes mirror multi-load routes (Task 6)
- preserve caller symbol order in both `data` and `missing_symbols`
- on 503, populate `domain="realtime_quotes"` and `market` in the error envelope

Add the route in `src/stockpilot/api/main.py`:

```python
class QuotesRequest(BaseModel):
    symbols: list[str]
    market: str = "us"


@app.post("/api/v1/quotes")
def realtime_quotes(request: QuotesRequest):
    gateway = _build_data_gateway()
    result = gateway.get_realtime_quotes(symbols=request.symbols, market=request.market)
    if result.error:
        raise HTTPException(status_code=result.error.http_status, detail=result.error.to_dict())
    return {"quotes": result.data, "data_status": result.to_status_dict()}
```

Wire the web watchlist call site in `src/stockpilot/web/static/js/app.js`. Add a `refreshWatchlistQuotes()` helper that:

- when `state.watchlist` is empty, clears the rail and returns
- `POST /api/v1/quotes` with `{symbols: state.watchlist, market: state.activeMarket}`
- on success, calls `consumeDataStatus(payload, {dedupeKey: "watchlist-quotes"})` and renders `payload.quotes` into `#rail-watchlist` (price + change_pct per symbol)
- on `503`, calls `formatApiError(err.detail)` and renders an inline degraded panel inside `#rail-watchlist` without toast spam
- is invoked after watchlist mutations and when the analysis page sets a new active symbol

Do **not** add polling or websocket behavior; phase-1 refresh is request-driven only.

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
python -m pytest tests/test_api_reliability.py tests/test_reliability_gateway.py tests/test_api_v2.py tests/test_smoke.py -v
```

Expected: PASS.

Manual browser smoke for the watchlist UX (do not commit the temporary override):

1. temporarily point `_build_data_gateway()` in `src/stockpilot/api/main.py` at `gateway_with_partial_quotes_batch()`
2. run `python -m stockpilot.cli serve`
3. load `/`, add two symbols to the watchlist, verify the missing symbol shows a degraded inline panel while the fresh symbol still renders a quote
4. point `_build_data_gateway()` at `gateway_with_unavailable_quotes_batch()` and verify the inline retry-guidance panel renders
5. revert the temporary override before committing

- [ ] **Step 5: Commit**

```bash
git add src/stockpilot/api/main.py src/stockpilot/data/reliability/gateway.py src/stockpilot/web/static/js/app.js tests/reliability_fakes.py tests/test_reliability_gateway.py tests/test_api_reliability.py
git commit -m "feat: add realtime quotes reliability touchpoint" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

## Chunk 3: CLI, agents, and regression

### Task 8: Wire the CLI commands to the gateway

**Files:**
- Modify: `src/stockpilot/cli.py:16-420`
- Create: `tests/test_cli_reliability.py`

- [ ] **Step 1: Write the failing test**

```python
from typer.testing import CliRunner
from stockpilot.cli import app


def test_analyze_prints_stale_warning(monkeypatch):
    monkeypatch.setattr("stockpilot.cli.build_default_data_gateway", lambda: gateway_returning_stale_analysis_data())
    result = CliRunner().invoke(app, ["analyze", "AAPL", "--market", "us"])
    assert result.exit_code == 0
    assert "Using stale cached data" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_cli_reliability.py::test_analyze_prints_stale_warning -v
```

Expected: FAIL because the CLI still builds `DataManager` instances inline and has no stale-warning path.

- [ ] **Step 3: Write minimal implementation**

```python
gateway = build_default_data_gateway()
result = gateway.get_price_history(...)
if result.status == "stale":
    console.print(f"[yellow]Using stale cached data from {result.source}[/yellow]")
df = result.data
```

Apply the same pattern only to the phase-1 CLI touchpoints named in the spec: `analyze`, `search`, `agent`, `backtest`, and `chart`.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
python -m pytest tests/test_cli_reliability.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stockpilot/cli.py tests/test_cli_reliability.py
git commit -m "feat: surface data reliability status in cli flows" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 9: Wire agent tools and run the regression suite

**Files:**
- Modify: `src/stockpilot/agents/tools/agent_tools.py:16-118`
- Modify: `tests/test_smoke.py:1-220`
- Modify: `tests/test_api_v2.py`
- Test: `tests/test_cli_reliability.py`

- [ ] **Step 1: Write the failing test**

```python
def test_get_stock_price_history_includes_data_status(monkeypatch):
    monkeypatch.setattr("stockpilot.agents.tools.agent_tools.build_default_data_gateway", lambda: gateway_returning_stale_history())
    payload = json.loads(get_stock_price_history.invoke({"symbol": "AAPL", "days": 30, "market": "us"}))
    assert payload["data_status"]["status"] == "stale"
    assert "data" in payload
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_cli_reliability.py::test_get_stock_price_history_includes_data_status -v
```

Expected: FAIL because the agent tools still return raw JSON without reliability metadata.

- [ ] **Step 3: Write minimal implementation**

```python
payload = {
    "data_status": result.to_status_dict(),
    "data": json.loads(df.tail(30).to_json(orient="records", date_format="iso")),
}
return json.dumps(payload, default=str)
```

Also add one smoke assertion that `build_default_data_gateway()` imports cleanly and can operate in stateless mode if the SQLite file cannot be opened.

- [ ] **Step 4: Run the focused regression suite**

Run:

```bash
python -m pytest tests/test_reliability_config.py tests/test_reliability_store.py tests/test_reliability_gateway.py tests/test_api_reliability.py tests/test_cli_reliability.py tests/test_api_v2.py tests/test_smoke.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/stockpilot/agents/tools/agent_tools.py tests/test_cli_reliability.py tests/test_api_v2.py tests/test_smoke.py
git commit -m "feat: expose reliability status to agent tools" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 10: Run the existing full repository checks once before handoff

**Files:**
- Modify: none
- Test: `tests/test_reliability_config.py`
- Test: `tests/test_reliability_store.py`
- Test: `tests/test_reliability_gateway.py`
- Test: `tests/test_api_reliability.py`
- Test: `tests/test_cli_reliability.py`
- Test: `tests/test_api_v2.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Run the data/API/CLI test suite together**

Run:

```bash
python -m pytest tests/test_reliability_config.py tests/test_reliability_store.py tests/test_reliability_gateway.py tests/test_api_reliability.py tests/test_cli_reliability.py tests/test_api_v2.py tests/test_smoke.py -q
```

Expected: PASS.

- [ ] **Step 2: Run the repo's default pytest command**

Run:

```bash
python -m pytest
```

Expected: PASS.

- [ ] **Step 3: Inspect `git status`**

Run:

```bash
git status --short
```

Expected: only the intended implementation files are modified.

- [ ] **Step 4: Commit the final polish if needed**

```bash
git add -A
git commit -m "test: finish reliability regression coverage" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

- [ ] **Step 5: Handoff note**

Record in the implementation PR/summary:

```text
Phase 1 ships one live source per domain/market plus stale-cache fallback only. Multi-source live merge remains intentionally out of scope.
```
