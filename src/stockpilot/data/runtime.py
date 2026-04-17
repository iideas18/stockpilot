"""Shared runtime builders used by CLI, API, and agents.

These helpers exist so that every entry point gets an identically-configured
``DataManager`` and ``DataGateway``. Failures to initialize the SQLite
reliability store gracefully degrade to a stateless in-memory shim rather than
taking the whole process down.
"""

from __future__ import annotations

import logging
from typing import Any

from stockpilot.config import get_settings
from stockpilot.data.manager import DataManager
from stockpilot.data.reliability.gateway import DataGateway
from stockpilot.data.reliability.registry import SourceRegistry
from stockpilot.data.reliability.shield import ReliabilityShield
from stockpilot.data.reliability.store import ReliabilityStore
from stockpilot.data.reliability.types import SourceHealth, SourceHealthState

logger = logging.getLogger(__name__)


class _StatelessReliabilityStore:
    """Null-object reliability store used when SQLite init fails.

    The shield treats any read as "cache miss" and any write as a no-op, so the
    gateway can still service requests — it just can't persist cache or health.
    """

    def __init__(self) -> None:
        self.stateless = True
        self.db_path = None

    def get_cache_entry(self, cache_key: str, now: str | None = None):  # noqa: ARG002
        return None

    def put_cache_entry(self, **kwargs: Any) -> None:  # noqa: ARG002
        return None

    def get_source_health(self, adapter: str, domain: str, market: str) -> SourceHealth:
        return SourceHealth(
            adapter=adapter,
            domain=domain,
            market=market,
            state=SourceHealthState.HEALTHY,
        )

    def record_source_success(self, adapter: str, domain: str, market: str, at_iso: str) -> SourceHealth:  # noqa: ARG002
        return self.get_source_health(adapter, domain, market)

    def record_source_failure(
        self, adapter: str, domain: str, market: str, error_type: str, at_iso: str  # noqa: ARG002
    ) -> SourceHealth:
        return self.get_source_health(adapter, domain, market)

    def begin_probe(self, adapter: str, domain: str, market: str, at_iso: str) -> bool:  # noqa: ARG002
        return True


def build_default_data_manager() -> DataManager:
    """Register all importable adapters with sensible defaults."""

    manager = DataManager()
    try:
        from stockpilot.data.adapters.akshare_adapter import AKShareAdapter

        manager.register_adapter(AKShareAdapter(), priority=True)
    except ImportError:
        logger.info("AKShareAdapter not available; skipping")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to register AKShareAdapter: %s", exc)

    try:
        from stockpilot.data.adapters.yfinance_adapter import YFinanceAdapter

        manager.register_adapter(YFinanceAdapter())
    except ImportError:
        logger.info("YFinanceAdapter not available; skipping")
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to register YFinanceAdapter: %s", exc)

    return manager


def build_default_data_gateway(data_manager: DataManager | None = None) -> DataGateway:
    """Build a gateway wired with the default registry, store, and manager."""

    settings = get_settings()
    reliability = settings.data.reliability

    try:
        store: Any = ReliabilityStore(reliability.sqlite_path)
    except Exception as exc:
        logger.warning(
            "ReliabilityStore initialization failed (%s); falling back to stateless store",
            exc,
        )
        store = _StatelessReliabilityStore()

    # ReliabilityStore itself flips ``stateless=True`` on sqlite errors caught
    # internally; callers rely on that flag.
    registry = SourceRegistry(reliability.source_order)
    manager = data_manager if data_manager is not None else build_default_data_manager()
    shield = ReliabilityShield(data_manager=manager, registry=registry, store=store)
    return DataGateway(shield=shield)
