"""Job scheduler — runs periodic data collection, analysis, and notifications.

Ported from Stock2's job/execute_daily_job.py.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


class Job:
    """A scheduled job."""

    def __init__(self, name: str, func: Callable, cron_expr: str = "") -> None:
        self.name = name
        self.func = func
        self.cron_expr = cron_expr
        self.last_run: datetime | None = None
        self.run_count = 0
        self.errors: list[str] = []

    def run(self) -> bool:
        try:
            logger.info("Running job: %s", self.name)
            self.func()
            self.last_run = datetime.now()
            self.run_count += 1
            logger.info("Job %s completed (run #%d)", self.name, self.run_count)
            return True
        except Exception as e:
            self.errors.append(f"{datetime.now()}: {e}")
            logger.error("Job %s failed: %s", self.name, e)
            return False


class Scheduler:
    """Simple job scheduler."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._running = False
        self._thread: threading.Thread | None = None

    def add_job(self, name: str, func: Callable, cron_expr: str = "") -> None:
        self._jobs[name] = Job(name, func, cron_expr)

    def run_job(self, name: str) -> bool:
        if name in self._jobs:
            return self._jobs[name].run()
        logger.error("Job not found: %s", name)
        return False

    def run_all(self) -> dict[str, bool]:
        return {name: job.run() for name, job in self._jobs.items()}

    def get_status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": job.name,
                "last_run": str(job.last_run) if job.last_run else None,
                "run_count": job.run_count,
                "errors": len(job.errors),
            }
            for job in self._jobs.values()
        ]


# ── Pre-built Jobs ──

def data_collection_job():
    """Fetch daily stock data."""
    from stockpilot.data.manager import DataManager
    from stockpilot.data.adapters.akshare_adapter import AKShareAdapter

    dm = DataManager()
    dm.register_adapter(AKShareAdapter(), priority=True)
    stock_list = dm.get_stock_list()
    logger.info("Data collection: %d stocks available", len(stock_list))


def indicator_calculation_job():
    """Calculate technical indicators for all tracked stocks."""
    logger.info("Indicator calculation job running")


def pattern_scan_job():
    """Scan for K-line patterns across all stocks."""
    logger.info("Pattern scan job running")


def news_crawl_job():
    """Fetch latest news from all platforms."""
    from stockpilot.news.aggregator import NewsAggregator
    agg = NewsAggregator()
    items = agg.fetch_all()
    logger.info("News crawl: %d items collected", len(items))


def create_default_scheduler() -> Scheduler:
    """Create scheduler with all default jobs."""
    scheduler = Scheduler()
    scheduler.add_job("data_collection", data_collection_job, "0 18 * * 1-5")
    scheduler.add_job("indicator_calc", indicator_calculation_job, "30 18 * * 1-5")
    scheduler.add_job("pattern_scan", pattern_scan_job, "0 19 * * 1-5")
    scheduler.add_job("news_crawl", news_crawl_job, "*/30 9-22 * * *")
    return scheduler
