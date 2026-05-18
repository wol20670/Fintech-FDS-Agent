"""
═══════════════════════════════════════════════════════════════
FDS API 라우터 (거래 심사 엔드포인트)
═══════════════════════════════════════════════════════════════
실시간 단건 심사 및 배치(다건) 분석 API를 제공합니다.

엔드포인트 목록:
  POST /api/v1/fds/evaluate         - 단건 거래 심사
  POST /api/v1/fds/batch            - 배치 거래 분석
  GET  /api/v1/fds/health           - FDS 서비스 상태 확인
  GET  /api/v1/fds/logs             - FDS 심사 이력 조회
  GET  /api/v1/fds/stats            - FDS 통계 대시보드용 데이터
═══════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import time
import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.schemas.telegram import (
    TransactionTelegram, TransactionResponse,
    BatchAnalysisRequest, BatchAnalysisResponse,
    RiskLevel, mask_account_id,
)
from backend.app.services.model_service_v2 import fds_service
from app.models.database import (
    insert_transaction, insert_fds_log,
    get_account_info, get_recent_transactions,
    get_db_connection,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/fds", tags=["FDS - 이상거래탐지"])


# ════════════════════════════════════════════
# 1. 단건 거래 심사 (실시간)
# ════════════════════════════════════════════

@router.post(
    "/evaluate",
    response_model=TransactionResponse,
    summary="단건 거래 FDS 심사",
    description="""
    하나의 거래 전문(Telegram)을 받아 실시간으로 사기 여부를 판단합니다.

    **처리 흐름:**
    1. 전문 수신 → 유효성 검증
    2. FDS 모델 추론 (ML 또는 Rule-Based)
    3. 리스크 등급 및 자율 대응 결정
    4. 거래 원장 및 FDS 로그 기록
    5. 결과 전문 반환

    **응답 시간 목표:** < 100ms (실제 은행 FDS 기준)
    """,
)
async def evaluate_transaction(telegram: TransactionTelegram):
    """
    단건 거래 FDS 심사 엔드포인트.

    은행 코어뱅킹 시스템에서 이체/출금 요청이 들어오면
    이 엔드포인트를 호출하여 거래의 사기 여부를 실시간으로 판단합니다.
    """
    try:
        # ── 1단계: 송금인 계좌 유효성 확인 ──
        sender_account = get_account_info(telegram.body.sender.account_id)
        if sender_account and sender_account["status"] != "ACTIVE":
            raise HTTPException(
                status_code=403,
                detail=f"송금 계좌 상태 이상: {sender_account['status']} "
                       f"(동결/해지된 계좌에서는 거래를 진행할 수 없습니다)"
            )

        # ── 2단계: FDS 모델 추론 ──
        response = fds_service.evaluate_transaction(telegram)

        # ── 3단계: 거래 원장 기록 ──
        # 금융권 원칙: 모든 거래 시도는 결과에 관계없이 원장에 기록
        try:
            body = telegram.body
            insert_transaction({
                "telegram_no": telegram.header.telegram_no,
                "step": 1,  # 실시간 거래
                "tx_type": body.transaction_type.value,
                "amount": body.amount,
                "sender_id": body.sender.account_id,
                "sender_bal_before": body.sender.current_balance,
                "sender_bal_after": body.sender.current_balance - body.amount,
                "receiver_id": body.receiver.account_id,
                "receiver_bal_before": body.receiver.current_balance,
                "receiver_bal_after": body.receiver.current_balance + body.amount,
                "is_fraud": 0,  # 실제 라벨은 나중에 확인 후 업데이트
                "channel_code": telegram.header.channel_code.value,
            })
        except Exception as e:
            # 원장 기록 실패해도 심사 결과는 반환
            # (거래 차단이 원장 기록보다 우선)
            logger.warning(f"[DB] 거래 원장 기록 실패: {e}")

        # ── 4단계: FDS 감사 로그 기록 ──
        try:
            insert_fds_log({
                "telegram_no": telegram.header.telegram_no,
                "risk_score": response.fds_result.risk_score,
                "risk_level": response.fds_result.risk_level.value,
                "action_taken": response.fds_result.action,
                "reason": response.fds_result.reason,
                "model_version": response.fds_result.model_version,
                "processing_ms": response.fds_result.processing_time_ms,
            })
        except Exception as e:
            logger.warning(f"[DB] FDS 로그 기록 실패: {e}")

        logger.info(
            f"[FDS] 심사 완료 | 전문번호={telegram.header.telegram_no} | "
            f"결과={response.fds_result.risk_level.value} | "
            f"조치={response.fds_result.action} | "
            f"소요={response.fds_result.processing_time_ms:.1f}ms"
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[FDS] 심사 중 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"FDS 심사 중 내부 오류 발생: {str(e)}")


# ════════════════════════════════════════════
# 2. 배치 거래 분석
# ════════════════════════════════════════════

@router.post(
    "/batch",
    response_model=BatchAnalysisResponse,
    summary="배치(다건) 거래 분석",
    description="""
    여러 건의 거래 전문을 한 번에 분석합니다.
    CSV 업로드 후 변환된 전문 목록이나, 야간 배치 분석에 활용됩니다.
    최대 10,000건까지 처리 가능합니다.
    """,
)
async def batch_analysis(request: BatchAnalysisRequest):
    """
    배치 분석 엔드포인트.
    야간 배치, 과거 데이터 재분석, CSV 업로드 분석 등에 활용.
    """
    start_time = time.time()
    results = []
    fraud_count = 0

    for telegram in request.transactions:
        try:
            response = fds_service.evaluate_transaction(telegram)
            results.append(response)

            if response.fds_result.risk_level in [
                RiskLevel.HIGH, RiskLevel.CRITICAL
            ]:
                fraud_count += 1
        except Exception as e:
            logger.error(f"[BATCH] 건별 심사 실패: {e}")
            continue

    total_time = (time.time() - start_time) * 1000

    logger.info(
        f"[BATCH] 배치 분석 완료 | "
        f"전체={len(request.transactions)}건 | "
        f"사기의심={fraud_count}건 | "
        f"소요={total_time:.1f}ms"
    )

    return BatchAnalysisResponse(
        total_count=len(results),
        fraud_count=fraud_count,
        safe_count=len(results) - fraud_count,
        results=results,
        processing_time_ms=round(total_time, 2),
    )


# ════════════════════════════════════════════
# 3. FDS 서비스 상태 확인
# ════════════════════════════════════════════

class HealthResponse(BaseModel):
    status: str = Field(..., description="서비스 상태")
    model_mode: str = Field(..., description="추론 엔진 모드 (ML/Rule-Based)")
    model_version: str = Field(..., description="모델 버전")
    db_status: str = Field(..., description="DB 연결 상태")
    timestamp: datetime = Field(default_factory=datetime.now)


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="FDS 서비스 상태 확인",
)
async def health_check():
    """서비스 상태 및 모델 로드 여부 확인."""
    # DB 상태 확인
    db_status = "OK"
    try:
        with get_db_connection() as conn:
            conn.execute("SELECT 1")
    except Exception:
        db_status = "ERROR"

    return HealthResponse(
        status="RUNNING",
        model_mode="ML Stacking Ensemble" if fds_service.is_ml_mode else "Rule-Based",
        model_version="FDS_Robust_Model_v1" if fds_service.is_ml_mode else "Rule_Based_v1",
        db_status=db_status,
    )


# ════════════════════════════════════════════
# 4. FDS 심사 이력 조회 (감사 추적용)
# ════════════════════════════════════════════

@router.get(
    "/logs",
    summary="FDS 심사 이력 조회",
    description="FDS 심사 결과 로그를 조회합니다. 감사 추적 및 모델 성능 분석에 활용.",
)
async def get_fds_logs(
    risk_level: str = Query(None, description="위험 등급 필터 (SAFE/LOW/MEDIUM/HIGH/CRITICAL)"),
    limit: int = Query(50, ge=1, le=500, description="조회 건수 (최대 500)"),
):
    """FDS 심사 이력 조회."""
    with get_db_connection() as conn:
        if risk_level:
            rows = conn.execute(
                """SELECT * FROM fds_logs
                   WHERE risk_level = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (risk_level, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM fds_logs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()

    return [dict(r) for r in rows]


# ════════════════════════════════════════════
# 5. FDS 통계 (대시보드용)
# ════════════════════════════════════════════

@router.get(
    "/stats",
    summary="FDS 통계 데이터",
    description="Streamlit 대시보드에서 호출할 통계 API. 위험 등급별 분포, 평균 처리 시간 등.",
)
async def get_fds_stats():
    """FDS 통계 데이터 반환."""
    with get_db_connection() as conn:
        # 위험 등급별 건수
        risk_dist = conn.execute(
            """SELECT risk_level, COUNT(*) as count
               FROM fds_logs GROUP BY risk_level"""
        ).fetchall()

        # 평균 처리 시간
        avg_time = conn.execute(
            "SELECT AVG(processing_ms) as avg_ms FROM fds_logs"
        ).fetchone()

        # 총 심사 건수
        total = conn.execute(
            "SELECT COUNT(*) as total FROM fds_logs"
        ).fetchone()

        # 최근 24시간 추이 (시간대별)
        hourly = conn.execute(
            """SELECT strftime('%H', created_at) as hour, COUNT(*) as count
               FROM fds_logs
               WHERE created_at >= datetime('now', 'localtime', '-24 hours')
               GROUP BY hour ORDER BY hour"""
        ).fetchall()

    return {
        "total_evaluations": total["total"] if total else 0,
        "avg_processing_ms": round(avg_time["avg_ms"], 2) if avg_time and avg_time["avg_ms"] else 0,
        "risk_distribution": {r["risk_level"]: r["count"] for r in risk_dist},
        "hourly_trend": [{"hour": h["hour"], "count": h["count"]} for h in hourly],
    }
