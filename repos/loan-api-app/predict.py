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
CLOUDSQL_CONNECTION_STRING = os.getenv("CLOUDSQL_CONNECTION_STRING")
CLOUDSQL_USER = os.getenv("CLOUDSQL_USER")
CLOUDSQL_PASSWORD = os.getenv("CLOUDSQL_PASSWORD")
CLOUDSQL_DBNAME = os.getenv("CLOUDSQL_DBNAME")
CLOUDSQL_TABLE_NAME = os.getenv("CLOUDSQL_TABLE_LOAN_RESULT", "loan_approval_result")

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
MAX_LOAN_AMOUNT                = 10_000_000   # 單筆貸款上限：1,000 萬


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
_cloudsql_conn = None

def _get_cloudsql_connection():
    """建立並回傳 CloudSQL 連線物件，使用延遲初始化。"""
    global _cloudsql_conn
    if _cloudsql_conn is not None:
        return _cloudsql_conn
    import pymysql
    if not CLOUDSQL_CONNECTION_STRING or not CLOUDSQL_USER or not CLOUDSQL_PASSWORD or not CLOUDSQL_DBNAME:
        logger.warning("未設定 CloudSQL 連線資訊，跳過資料庫寫入")
        return None
    try:
        _cloudsql_conn = pymysql.connect(
            host=CLOUDSQL_CONNECTION_STRING,
            user=CLOUDSQL_USER,
            password=CLOUDSQL_PASSWORD,
            database=CLOUDSQL_DBNAME,
            charset='utf8mb4',
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True
        )
        return _cloudsql_conn
    except Exception as exc:
        logger.error("CloudSQL 連線失敗：%s", exc)
        return None


def persist_loan_decision(decision: LoanDecision) -> None:
    """將核貸結果寫入 CloudSQL，供後續報表與審計分析使用。"""
    conn = _get_cloudsql_connection()
    if conn is None:
        return
    sql = f"""
    INSERT INTO {CLOUDSQL_TABLE_NAME} (application_id, customer_id, vip_status, interest_rate, approved, approved_at)
    VALUES (%s, %s, %s, %s, %s, %s)
    """
    params = (
        decision.application_id,
        decision.customer_id,
        decision.vip_status,
        decision.interest_rate,
        decision.approved,
        decision.approved_at.strftime('%Y-%m-%d %H:%M:%S')
    )
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
        logger.info("CloudSQL 寫入完成 | table=%s | application_id=%s", CLOUDSQL_TABLE_NAME, decision.application_id)
    except Exception as exc:
        logger.error("CloudSQL 寫入失敗 | table=%s | application_id=%s | error=%s", CLOUDSQL_TABLE_NAME, decision.application_id, exc)


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
