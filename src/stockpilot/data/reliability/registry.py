"""Source registry: maps (domain, market) to an allowlist of adapter names.

Phase-1 is static config only: the registry reflects whatever is in
``settings.data.reliability.source_order``. No discovery, no implicit
fallbacks beyond that list.
"""

from __future__ import annotations

from typing import Iterable

from stockpilot.data.reliability.types import DomainId


class SourceRegistry:
    """Static allowlist of adapter names per (domain, market)."""

    def __init__(self, source_order: dict[str, dict[str, list[str]]] | None) -> None:
        self._source_order: dict[str, dict[str, list[str]]] = {}
        for domain, markets in (source_order or {}).items():
            if not isinstance(markets, dict):
                continue
            bucket: dict[str, list[str]] = {}
            for market, adapters in markets.items():
                if isinstance(adapters, Iterable) and not isinstance(adapters, (str, bytes)):
                    bucket[str(market)] = [str(a) for a in adapters]
            self._source_order[str(domain)] = bucket

    @staticmethod
    def _coerce_domain(domain: DomainId | str) -> str:
        if isinstance(domain, DomainId):
            return domain.value
        return str(domain)

    def get_adapter_order(self, domain: DomainId | str, market: str) -> list[str]:
        domain_key = self._coerce_domain(domain)
        market_key = str(market)
        bucket = self._source_order.get(domain_key, {})
        return list(bucket.get(market_key, []))
