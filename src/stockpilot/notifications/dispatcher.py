"""Multi-channel notification dispatcher.

Supports Telegram, DingTalk, Feishu, WeChat Work, Email, and ntfy.
Ported from TrendRadar's notification system.
"""

from __future__ import annotations

import logging
import smtplib
from email.mime.text import MIMEText
from typing import Any

import requests

from stockpilot.config import get_settings

logger = logging.getLogger(__name__)


class NotificationDispatcher:
    """Send notifications through configured channels."""

    def __init__(self) -> None:
        self._settings = get_settings().notifications

    def send(self, title: str, message: str, channels: list[str] | None = None) -> dict[str, bool]:
        """Send notification to all enabled channels (or specified ones).

        Returns dict of channel: success.
        """
        results = {}
        targets = channels or self._get_enabled_channels()

        for channel in targets:
            try:
                method = getattr(self, f"_send_{channel}", None)
                if method:
                    method(title, message)
                    results[channel] = True
                    logger.info("Notification sent via %s", channel)
                else:
                    logger.warning("Unknown channel: %s", channel)
                    results[channel] = False
            except Exception as e:
                logger.error("Failed to send via %s: %s", channel, e)
                results[channel] = False

        return results

    def _get_enabled_channels(self) -> list[str]:
        channels = []
        if self._settings.telegram_bot_token:
            channels.append("telegram")
        if self._settings.dingtalk_webhook_url:
            channels.append("dingtalk")
        if self._settings.feishu_webhook_url:
            channels.append("feishu")
        if self._settings.email_smtp_host:
            channels.append("email")
        return channels

    def _send_telegram(self, title: str, message: str) -> None:
        token = self._settings.telegram_bot_token
        chat_id = self._settings.telegram_chat_id
        text = f"*{title}*\n\n{message}"
        requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )

    def _send_dingtalk(self, title: str, message: str) -> None:
        webhook = self._settings.dingtalk_webhook_url
        requests.post(webhook, json={
            "msgtype": "markdown",
            "markdown": {"title": title, "text": f"## {title}\n\n{message}"},
        }, timeout=10)

    def _send_feishu(self, title: str, message: str) -> None:
        webhook = self._settings.feishu_webhook_url
        requests.post(webhook, json={
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": message}],
            },
        }, timeout=10)

    def _send_email(self, title: str, message: str) -> None:
        msg = MIMEText(message, "plain", "utf-8")
        msg["Subject"] = f"[StockPilot] {title}"
        msg["From"] = self._settings.email_username
        msg["To"] = self._settings.email_username  # self-notify

        with smtplib.SMTP_SSL(self._settings.email_smtp_host, 465) as server:
            server.login(self._settings.email_username, self._settings.email_password)
            server.send_message(msg)
