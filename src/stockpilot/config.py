"""Centralized configuration loader for StockPilot.

Loads settings from config/settings.yaml and .env, providing a single
Settings object used throughout the application.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"

load_dotenv(PROJECT_ROOT / ".env")


_NEWS_PLATFORM_ALIASES = {
    "reddit": "reddit_finance",
}


def _normalize_news_platforms(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if value is None:
        return []

    if isinstance(value, str):
        raw_items = value.split(",")
    else:
        raw_items = value

    normalized: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        platform = str(item).strip().lower()
        if not platform:
            continue
        platform = _NEWS_PLATFORM_ALIASES.get(platform, platform)
        if platform not in seen:
            normalized.append(platform)
            seen.add(platform)

    return normalized


def _load_yaml_config() -> dict[str, Any]:
    config_path = CONFIG_DIR / "settings.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    return {}


class DatabaseSettings(BaseSettings):
    url: str = Field(default="sqlite:///stockpilot.db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")


class LLMSettings(BaseSettings):
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="", alias="OPENAI_BASE_URL")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    xai_api_key: str = Field(default="", alias="XAI_API_KEY")
    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    azure_api_key: str = Field(default="", alias="AZURE_OPENAI_API_KEY")
    azure_endpoint: str = Field(default="", alias="AZURE_OPENAI_ENDPOINT")
    azure_api_version: str = Field(default="2024-02-01", alias="AZURE_OPENAI_API_VERSION")

    default_provider: str = "openai"
    default_model: str = "gpt-4o"
    analyst_model: str = "gpt-4o-mini"
    debate_model: str = "gpt-4o"
    temperature: float = 0.7
    max_tokens: int = 4096


class DataSettings(BaseSettings):
    primary_source: str = "akshare"
    cache_backend: str = "redis"
    cache_ttl_seconds: int = 3600
    price_ttl_seconds: int = 300

    alpha_vantage_api_key: str = Field(default="", alias="ALPHA_VANTAGE_API_KEY")
    tushare_token: str = Field(default="", alias="TUSHARE_TOKEN")


class NewsSettings(BaseSettings):
    enabled: bool = True
    crawl_interval_minutes: int = 30
    platforms: list[str] = Field(default_factory=lambda: ["weibo", "douyin", "zhihu", "reddit_finance", "hackernews"])

    reddit_client_id: str = Field(default="", alias="REDDIT_CLIENT_ID")
    reddit_client_secret: str = Field(default="", alias="REDDIT_CLIENT_SECRET")
    reddit_user_agent: str = Field(default="stockpilot/0.1.0", alias="REDDIT_USER_AGENT")


class NotificationSettings(BaseSettings):
    enabled: bool = False
    telegram_bot_token: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    telegram_chat_id: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    dingtalk_webhook_url: str = Field(default="", alias="DINGTALK_WEBHOOK_URL")
    feishu_webhook_url: str = Field(default="", alias="FEISHU_WEBHOOK_URL")
    email_smtp_host: str = Field(default="", alias="EMAIL_SMTP_HOST")
    email_username: str = Field(default="", alias="EMAIL_USERNAME")
    email_password: str = Field(default="", alias="EMAIL_PASSWORD")


class TradingSettings(BaseSettings):
    mode: str = "paper"  # paper | live
    initial_capital: float = 1_000_000
    commission_rate: float = 0.0003
    max_position_pct: float = 0.1
    daily_loss_limit_pct: float = 0.02


class APISettings(BaseSettings):
    host: str = Field(default="0.0.0.0", alias="APP_HOST")
    port: int = Field(default=8000, alias="APP_PORT")
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]


class Settings:
    """Main settings container — aggregates all sub-settings and YAML config."""

    def __init__(self) -> None:
        self._yaml = _load_yaml_config()
        self.db = DatabaseSettings()
        self.llm = self._build_llm_settings()
        self.data = self._build_data_settings()
        self.news = self._build_news_settings()
        self.notifications = NotificationSettings()
        self.trading = TradingSettings()
        self.api = APISettings()

        self.app_name: str = self._yaml.get("app", {}).get("name", "StockPilot")
        self.app_env: str = os.getenv("APP_ENV", self._yaml.get("app", {}).get("env", "development"))
        self.log_level: str = os.getenv("LOG_LEVEL", self._yaml.get("app", {}).get("log_level", "INFO"))

    def _build_llm_settings(self) -> LLMSettings:
        agent_cfg = self._yaml.get("agents", {}).get("llm", {})
        settings = LLMSettings()
        for key in ("default_provider", "default_model", "analyst_model", "debate_model", "temperature", "max_tokens"):
            if key in agent_cfg:
                setattr(settings, key, agent_cfg[key])
        return settings

    def _build_data_settings(self) -> DataSettings:
        data_cfg = self._yaml.get("data", {})
        settings = DataSettings()
        if "primary_source" in data_cfg:
            settings.primary_source = data_cfg["primary_source"]
        cache_cfg = data_cfg.get("cache", {})
        if "backend" in cache_cfg:
            settings.cache_backend = cache_cfg["backend"]
        if "ttl_seconds" in cache_cfg:
            settings.cache_ttl_seconds = cache_cfg["ttl_seconds"]
        return settings

    def _build_news_settings(self) -> NewsSettings:
        news_cfg = self._yaml.get("news", {})
        settings = NewsSettings()
        if "enabled" in news_cfg:
            settings.enabled = news_cfg["enabled"]
        if "crawl_interval_minutes" in news_cfg:
            settings.crawl_interval_minutes = news_cfg["crawl_interval_minutes"]
        env_platforms = os.getenv("STOCKPILOT_NEWS_PLATFORMS")
        if env_platforms is None:
            env_platforms = os.getenv("NEWS_PLATFORMS")
        if env_platforms is not None:
            settings.platforms = _normalize_news_platforms(env_platforms)
        elif "platforms" in news_cfg:
            settings.platforms = _normalize_news_platforms(news_cfg["platforms"])
        return settings

    @property
    def yaml_config(self) -> dict[str, Any]:
        return self._yaml


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Get the singleton Settings instance."""
    return Settings()
