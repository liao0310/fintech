"""
loan-api 核心邏輯 — 自動核貸預測模組

本模組負責：
1. 呼叫 vip-svc 取得客戶 VIP 等級
2. 根據 VIP 等級計算個人化貸款利率
3. 執行信用評估與核貸決策
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# ── 連線設定 ──────────────────────────────────────────────
VIP_SVC_URL     = os.getenv("VIP_SVC_URL", "https://vip-svc-internal.asia-east1.run.app")
VIP_SVC_TIMEOUT = int(os.getenv("VIP_SVC_TIMEOUT_SEC", "10"))
BQ_PROJECT_ID   = (
    os.getenv("BQ_PROJECT_ID")
    or os.getenv("GOOGLE_CLOUD_PROJECT")
    or os.getenv("GCP_PROJECT")
)
BQ_DATASET_ID   = os.getenv("BQ_DATASET_ID", "lending_ops")
BQ_TABLE_NAME   = os.getenv("BQ_TABLE_LOAN_RESULT", "loan_approval_result")

# ── 利率設定 (%) ──────────────────────────────────────────
BASE_RATE_VIP_A    = float(os.getenv("BASE_RATE_VIP_A",    "1.5"))
BASE_RATE_VIP_B    = float(os.getenv("BASE_RATE_VIP_B",    "2.2"))
BASE_RATE_STANDARD = float(os.getenv("BASE_RATE_STANDARD", "3.8"))

RATE_TABLE = {
    "VIP_A":    BASE_RATE_VIP_A,
    "VIP_B":    BASE_RATE_VIP_B,
    "STANDARD": BASE_RATE_STANDARD,
}

# ── 信用評分門檻 ──────────────────────────────────────────
MIN_CREDIT_SCORE_FOR_APPROVAL = 600
MAX_LOAN_AMOUNT                = 5_000_000   # 單筆貸款上限：500 萬


@dataclass
class LoanApplication:
    """貸款申請資料"""
    application_id: str
    customer_id: str
    requested_amount: float   # 申請金額（新台幣）
    credit_score: int
    annual_income: float      # 年收入（新台幣）


@dataclass
class LoanDecision:
    """核貸決策結果"""
    application_id: str
    customer_id: str
    vip_status: str
    interest_rate: float
    approved: bool
    rejection_reason: Optional[str]
    approved_at: datetime


def _build_http_session() -> requests.Session:
    """建立帶有重試機制的 HTTP Session。"""
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


_session = _build_http_session()
_bigquery_client = None


def _get_bigquery_client():
    """延遲建立 BigQuery client，避免模組載入時就依賴 GCP 環境。"""
    global _bigquery_client

    if _bigquery_client is not None:
        return _bigquery_client

    if not BQ_PROJECT_ID:
        logger.warning("未設定 BQ_PROJECT_ID / GOOGLE_CLOUD_PROJECT，跳過 BigQuery 寫入")
        return None

    try:
        from google.cloud import bigquery
    except ImportError:
        logger.warning("google-cloud-bigquery 尚未安裝，跳過 BigQuery 寫入")
        return None

    _bigquery_client = bigquery.Client(project=BQ_PROJECT_ID)
    return _bigquery_client


def persist_loan_decision(decision: LoanDecision) -> None:
    """將核貸結果寫入 BigQuery，供後續報表與審計分析使用。"""
    client = _get_bigquery_client()
    if client is None:
        return

    table_ref = f"{BQ_PROJECT_ID}.{BQ_DATASET_ID}.{BQ_TABLE_NAME}"
    row = {
        "application_id": decision.application_id,
        "customer_id": decision.customer_id,
        "vip_status": decision.vip_status,
        "interest_rate": decision.interest_rate,
        "approved": decision.approved,
        "approved_at": decision.approved_at.isoformat(),
    }

    try:
        errors = client.insert_rows_json(table_ref, [row])
    except Exception as exc:
        logger.error("BigQuery 寫入失敗 | table=%s | application_id=%s | error=%s", table_ref, decision.application_id, exc)
        return

    if errors:
        logger.error("BigQuery 寫入失敗 | table=%s | application_id=%s | errors=%s", table_ref, decision.application_id, errors)
        return

    logger.info("BigQuery 寫入完成 | table=%s | application_id=%s", table_ref, decision.application_id)


def fetch_vip_status(customer_id: str) -> str:
    """
    呼叫 vip-svc API 取得指定客戶的 VIP 等級。

    Args:
        customer_id: 客戶識別碼

    Returns:
        VIP 等級字串（VIP_A / VIP_B / STANDARD）
    """
    endpoint = f"{VIP_SVC_URL}/api/v1/classify"
    try:
        response = _session.post(
            endpoint,
            json={"customer_id": customer_id},
            timeout=VIP_SVC_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        vip_status = data.get("vip_status", "STANDARD")
        logger.info("vip-svc 回傳 | customer_id=%s | vip_status=%s", customer_id, vip_status)
        return vip_status

    except requests.exceptions.Timeout:
        logger.error("呼叫 vip-svc 逾時，customer_id=%s，降級為 STANDARD", customer_id)
        return "STANDARD"
    except requests.exceptions.RequestException as exc:
        logger.error("呼叫 vip-svc 發生錯誤：%s，降級為 STANDARD", exc)
        return "STANDARD"


def calculate_interest_rate(vip_status: str, credit_score: int) -> float:
    """
    根據 VIP 等級與信用評分計算貸款利率。

    Args:
        vip_status:   VIP 等級
        credit_score: 信用評分

    Returns:
        最終貸款利率（百分比）
    """
    base_rate = RATE_TABLE.get(vip_status, BASE_RATE_STANDARD)

    # 信用評分加分邏輯
    if credit_score >= 800:
        credit_adjustment = -0.3
    elif credit_score >= 750:
        credit_adjustment = -0.1
    elif credit_score < 650:
        credit_adjustment = +0.5
    else:
        credit_adjustment = 0.0

    final_rate = round(base_rate + credit_adjustment, 2)
    logger.info(
        "利率計算 | vip_status=%s | credit_score=%d | base_rate=%.2f%% | adjustment=%.2f%% | final=%.2f%%",
        vip_status, credit_score, base_rate, credit_adjustment, final_rate,
    )
    return final_rate


def evaluate_loan(application: LoanApplication) -> LoanDecision:
    """
    執行完整核貸評估流程。

    Args:
        application: 貸款申請資料

    Returns:
        核貸決策結果
    """
    # 步驟 1：向 vip-svc 查詢 VIP 等級
    vip_status = fetch_vip_status(application.customer_id)

    # 步驟 2：計算個人化利率
    interest_rate = calculate_interest_rate(vip_status, application.credit_score)

    # 步驟 3：核貸判斷
    rejection_reason: Optional[str] = None
    approved = True

    if application.credit_score < MIN_CREDIT_SCORE_FOR_APPROVAL:
        approved = False
        rejection_reason = f"信用評分 {application.credit_score} 低於最低門檻 {MIN_CREDIT_SCORE_FOR_APPROVAL}"

    elif application.requested_amount > MAX_LOAN_AMOUNT:
        approved = False
        rejection_reason = f"申請金額 {application.requested_amount:,.0f} 元超過單筆上限 {MAX_LOAN_AMOUNT:,} 元"

    elif application.requested_amount > application.annual_income * 10:
        approved = False
        rejection_reason = "申請金額超過年收入 10 倍，風險過高"

    logger.info(
        "核貸決策 | application_id=%s | approved=%s | rate=%.2f%% | vip=%s",
        application.application_id, approved, interest_rate, vip_status,
    )

    decision = LoanDecision(
        application_id=application.application_id,
        customer_id=application.customer_id,
        vip_status=vip_status,
        interest_rate=interest_rate,
        approved=approved,
        rejection_reason=rejection_reason,
        approved_at=datetime.now(timezone.utc),
    )
    persist_loan_decision(decision)
    return decision
