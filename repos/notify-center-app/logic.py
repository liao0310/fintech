"""
notify-center 核心業務邏輯 — 通知派送與偏好管理模組
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

CHANNEL_EMAIL = "EMAIL"
CHANNEL_SMS = "SMS"
CHANNEL_PUSH = "PUSH"
DEFAULT_LANGUAGE = "zh-TW"


@dataclass
class NotificationPreference:
    """使用者通知偏好設定。"""
    customer_id: str
    enabled_channels: list[str] = field(default_factory=lambda: [CHANNEL_EMAIL])
    language: str = DEFAULT_LANGUAGE
    quiet_hours_enabled: bool = True


@dataclass
class NotificationTask:
    """待送出的通知任務。"""
    customer_id: str
    template_id: str
    channel: str
    payload: dict[str, str]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def choose_delivery_channel(preference: NotificationPreference) -> str:
    """依偏好決定通知派送通道。"""
    for channel in [CHANNEL_PUSH, CHANNEL_SMS, CHANNEL_EMAIL]:
        if channel in preference.enabled_channels:
            logger.info("選擇通知通道 | customer_id=%s | channel=%s", preference.customer_id, channel)
            return channel
    return CHANNEL_EMAIL


def build_notification_task(customer_id: str, template_id: str, preference: NotificationPreference) -> NotificationTask:
    """建立通知派送任務。"""
    channel = choose_delivery_channel(preference)
    payload = {
        "template_id": template_id,
        "language": preference.language,
        "quiet_hours_enabled": str(preference.quiet_hours_enabled).lower(),
    }
    task = NotificationTask(
        customer_id=customer_id,
        template_id=template_id,
        channel=channel,
        payload=payload,
    )
    logger.info("通知任務建立完成 | customer_id=%s | template_id=%s | channel=%s", customer_id, template_id, channel)
    return task


def batch_prepare_notifications(customer_ids: list[str], template_id: str) -> list[NotificationTask]:
    """批次產生通知任務。"""
    tasks: list[NotificationTask] = []
    for customer_id in customer_ids:
        preference = NotificationPreference(customer_id=customer_id)
        tasks.append(build_notification_task(customer_id, template_id, preference))
    return tasks