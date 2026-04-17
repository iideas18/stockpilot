"""Typed errors used by the data reliability layer."""

from __future__ import annotations


class CallerDataError(ValueError):
    """Caller supplied an invalid request (bad symbol, bad date range, etc.)."""


class DisabledDataSourceError(RuntimeError):
    """The requested data source is disabled by configuration."""


class CoverageEmptyData(LookupError):
    """Source returned successfully but had no data covering the request."""


class SourceResponseError(RuntimeError):
    """Source responded but the payload was malformed or unusable."""
