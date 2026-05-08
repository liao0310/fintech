"""
vip-svc 核心業務邏輯 — 高端客戶識別模組
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── VIP 分級門檻常數 (AUM 單位：新台幣) ─────────────────────
VIP_THRESHOLD_A = 5_000_000   # 500 萬以上 → VIP_A
VIP_THRESHOLD_B = 1_000_000   # 100 萬以上 → VIP_B
STATUS_VIP_A    = "VIP_A"
STATUS_VIP_B    = "VIP_B"
STATUS_STANDARD = "STANDARD"


@dataclass
class CustomerProfile:
    """客戶基本資料"""
    customer_id: str
    aum: float                         # 資產管理規模（新台幣）
    credit_score: int = 700
    is_active: bool = True
    tags: list[str] = field(default_factory=list)


@dataclass
class VipClassificationResult:
    """VIP 分類結果"""
    customer_id: str
    aum_value: float
    vip_status: str
    classified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str = ""


def classify_vip_status(user_aum: float) -> str:
    """
    根據客戶 AUM 判斷 VIP 等級。

    Args:
        user_aum: 客戶資產管理規模（新台幣）

    Returns:
        VIP 等級字串：VIP_A / VIP_B / STANDARD
    """
    if user_aum > 5_000_000:
        status = STATUS_VIP_A
    elif user_aum > 1_000_000:
        status = STATUS_VIP_B
    else:
        status = STATUS_STANDARD
        status = STATUS_STANDARD

    logger.info(
        "VIP 分類完成 | aum=%.2f | status=%s | threshold_a=%d",
        user_aum,
        status,
        VIP_THRESHOLD_A,
    )
    return status


def process_customer(profile: CustomerProfile) -> VipClassificationResult:
    """
    處理單一客戶的 VIP 識別流程。

    Args:
        profile: 客戶基本資料

    Returns:
        VIP 分類結果
    """
    if not profile.is_active:
        logger.warning("客戶 %s 為非活躍狀態，跳過分類", profile.customer_id)
        return VipClassificationResult(
            customer_id=profile.customer_id,
            aum_value=profile.aum,
            vip_status=STATUS_STANDARD,
            reason="帳戶非活躍",
        )

    vip_status = classify_vip_status(profile.aum)

    reason_map = {
        STATUS_VIP_A: f"AUM {profile.aum:,.0f} 元超過 {VIP_THRESHOLD_A:,} 元門檻",
        STATUS_VIP_B: f"AUM {profile.aum:,.0f} 元超過 {VIP_THRESHOLD_B:,} 元門檻",
        STATUS_STANDARD: f"AUM {profile.aum:,.0f} 元未達任何 VIP 門檻",
    }

    return VipClassificationResult(
        customer_id=profile.customer_id,
        aum_value=profile.aum,
        vip_status=vip_status,
        reason=reason_map[vip_status],
    )


def batch_classify(profiles: list[CustomerProfile]) -> list[VipClassificationResult]:
    """
    批次處理多位客戶的 VIP 分類。

    Args:
        profiles: 客戶資料清單

    Returns:
        VIP 分類結果清單
    """
    results: list[VipClassificationResult] = []
    for profile in profiles:
        try:
            result = process_customer(profile)
            results.append(result)
        except Exception as exc:
            logger.error("處理客戶 %s 時發生錯誤：%s", profile.customer_id, exc)
    return results


def get_rate_discount(vip_status: str) -> float:
    """
    根據 VIP 等級回傳利率折扣（百分比點數）。

    Args:
        vip_status: VIP 等級字串

    Returns:
        利率優惠折扣（百分比點數，例如 1.5 代表降低 1.5%）
    """
    discount_map = {
        STATUS_VIP_A: 2.3,
        STATUS_VIP_B: 1.6,
        STATUS_STANDARD: 0.0,
    }
    return discount_map.get(vip_status, 0.0)
