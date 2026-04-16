"""Multi-platform news aggregator.

Fetches trending news from 10+ platforms. Ported from TrendRadar.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import requests

logger = logging.getLogger(__name__)


PLATFORM_ALIASES = {
    "reddit": "reddit_finance",
}

PLATFORM_ENV_VARS = ("STOCKPILOT_NEWS_PLATFORMS", "NEWS_PLATFORMS")


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    rank: int = 0
    hot_score: float = 0.0
    published_at: datetime | None = None
    summary: str = ""


@dataclass
class PlatformConfig:
    name: str
    api_url: str
    enabled: bool = True
    parser: str = "default"


# Platform API endpoints (using public APIs and aggregators)
PLATFORMS = {
    "weibo": PlatformConfig("微博热搜", "https://weibo.com/ajax/side/hotSearch", parser="weibo"),
    "zhihu": PlatformConfig("知乎热榜", "https://www.zhihu.com/api/v3/feed/topstory/hot-lists/total", parser="zhihu"),
    "douyin": PlatformConfig("抖音热点", "https://www.douyin.com/aweme/v1/web/hot/search/list/", parser="douyin"),
    "hackernews": PlatformConfig("Hacker News", "https://hacker-news.firebaseio.com/v0/topstories.json", parser="hackernews"),
    "reddit_finance": PlatformConfig("Reddit Finance", "", parser="reddit"),
}


def _normalize_platforms(platforms: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for platform in platforms:
        key = PLATFORM_ALIASES.get(platform.strip().lower(), platform.strip().lower())
        if not key or key in seen:
            continue
        normalized.append(key)
        seen.add(key)
    return normalized


def _load_platforms_from_env() -> list[str] | None:
    for env_name in PLATFORM_ENV_VARS:
        raw_value = os.getenv(env_name)
        if raw_value is None:
            continue
        return _normalize_platforms(raw_value.split(","))
    return None


def _load_configured_platforms() -> list[str]:
    env_platforms = _load_platforms_from_env()
    if env_platforms is not None:
        return env_platforms

    try:
        from stockpilot.config import get_settings

        configured = get_settings().news.platforms
    except Exception as exc:
        logger.debug("Falling back to built-in news platforms: %s", exc)
        configured = list(PLATFORMS.keys())

    platforms = _normalize_platforms(configured)
    if platforms:
        return platforms
    return list(PLATFORMS.keys())


class NewsAggregator:
    """Aggregates news from multiple platforms.

    Usage:
        aggregator = NewsAggregator(platforms=["hackernews", "reddit_finance"])
        news = aggregator.fetch_all()
    """

    def __init__(
        self,
        platforms: list[str] | None = None,
        keyword_filter: list[str] | None = None,
        max_items_per_platform: int = 20,
        timeout: int = 10,
    ):
        self.platforms = _normalize_platforms(platforms) if platforms is not None else _load_configured_platforms()
        self.keyword_filter = keyword_filter or []
        self.max_items = max_items_per_platform
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "StockPilot/0.1.0",
            "Accept": "application/json",
        })

    def fetch_all(self) -> list[NewsItem]:
        """Fetch news from all configured platforms."""
        all_news: list[NewsItem] = []
        for platform_key in self.platforms:
            try:
                items = self._fetch_platform(platform_key)
                all_news.extend(items)
                logger.info("Fetched %d items from %s", len(items), platform_key)
            except Exception as e:
                logger.warning("Failed to fetch from %s: %s", platform_key, e)
        if self.keyword_filter:
            all_news = self._filter_by_keywords(all_news)
        return sorted(all_news, key=lambda x: x.hot_score, reverse=True)

    def _fetch_platform(self, platform_key: str) -> list[NewsItem]:
        """Fetch from a single platform."""
        platform_key = PLATFORM_ALIASES.get(platform_key.strip().lower(), platform_key.strip().lower())
        if platform_key not in PLATFORMS:
            return []
        config = PLATFORMS[platform_key]
        if not config.enabled:
            return []

        if config.parser == "hackernews":
            return self._parse_hackernews()
        elif config.parser == "reddit":
            return self._parse_reddit()
        elif config.parser == "weibo":
            return self._parse_weibo(config.api_url)
        else:
            return self._parse_generic(config)

    def _parse_hackernews(self) -> list[NewsItem]:
        """Fetch top stories from Hacker News."""
        try:
            resp = self._session.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json",
                timeout=self.timeout,
            )
            story_ids = resp.json()[:self.max_items]
            items = []
            for i, sid in enumerate(story_ids[:10]):  # Limit API calls
                story_resp = self._session.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                    timeout=self.timeout,
                )
                story = story_resp.json()
                if story and story.get("title"):
                    items.append(NewsItem(
                        title=story["title"],
                        url=story.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                        source="Hacker News",
                        rank=i + 1,
                        hot_score=story.get("score", 0),
                    ))
            return items
        except Exception as e:
            logger.warning("HN fetch failed: %s", e)
            return []

    def _parse_reddit(self) -> list[NewsItem]:
        """Fetch from Reddit finance subreddits (public JSON API)."""
        subreddits = ["wallstreetbets", "stocks", "investing"]
        items = []
        for sub in subreddits:
            try:
                resp = self._session.get(
                    f"https://www.reddit.com/r/{sub}/hot.json?limit=10",
                    timeout=self.timeout,
                )
                data = resp.json()
                for i, post in enumerate(data.get("data", {}).get("children", [])):
                    pd = post.get("data", {})
                    if pd.get("title"):
                        items.append(NewsItem(
                            title=pd["title"],
                            url=f"https://reddit.com{pd.get('permalink', '')}",
                            source=f"r/{sub}",
                            rank=i + 1,
                            hot_score=pd.get("score", 0),
                        ))
            except Exception as e:
                logger.warning("Reddit r/%s fetch failed: %s", sub, e)
        return items

    def _parse_weibo(self, url: str) -> list[NewsItem]:
        """Fetch Weibo hot search."""
        try:
            resp = self._session.get(url, timeout=self.timeout)
            data = resp.json()
            items = []
            for i, item in enumerate(data.get("data", {}).get("realtime", [])[:self.max_items]):
                items.append(NewsItem(
                    title=item.get("word", ""),
                    url=f"https://s.weibo.com/weibo?q={item.get('word', '')}",
                    source="微博",
                    rank=i + 1,
                    hot_score=item.get("num", 0),
                ))
            return items
        except Exception as e:
            logger.warning("Weibo fetch failed: %s", e)
            return []

    def _parse_generic(self, config: PlatformConfig) -> list[NewsItem]:
        """Generic parser for simple JSON APIs."""
        try:
            resp = self._session.get(config.api_url, timeout=self.timeout)
            return []  # Override per platform
        except Exception:
            return []

    def _filter_by_keywords(self, items: list[NewsItem]) -> list[NewsItem]:
        """Filter news items by keyword list."""
        if not self.keyword_filter:
            return items
        return [
            item for item in items
            if any(kw.lower() in item.title.lower() for kw in self.keyword_filter)
        ]

    def get_financial_news_summary(self) -> str:
        """Get a formatted summary of financial news for agent consumption."""
        items = self.fetch_all()
        if not items:
            return "No recent financial news available."
        lines = [f"Top Financial News ({datetime.now().strftime('%Y-%m-%d %H:%M')}):\n"]
        for i, item in enumerate(items[:15], 1):
            lines.append(f"{i}. [{item.source}] {item.title} (score: {item.hot_score})")
        return "\n".join(lines)
