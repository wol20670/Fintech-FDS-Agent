"""
═══════════════════════════════════════════════════════════════
계좌/고객 관리 API 라우터
═══════════════════════════════════════════════════════════════
테스트 및 대시보드에서 사용할 계좌/고객 조회 엔드포인트.

※ 실제 은행에서는 이 API가 '코어뱅킹 시스템'에 해당하며,
   FDS와는 별도 시스템으로 운영됩니다.
   여기서는 편의상 하나의 서버에 통합했습니다.
═══════════════════════════════════════════════════════════════
"""

from fastapi import APIRouter, HTTPException, Query
from app.models.database import (
    get_db_connection, get_account_info,
    get_recent_transactions, get_tx_stats,
)
from app.schemas.telegram import mask_account_id

router = APIRouter(prefix="/api/v1/accounts", tags=["계좌/고객 관리"])


@router.get(
    "/",
    summary="전체 계좌 목록 조회",
    description="DB에 등록된 전체 계좌 목록을 반환합니다. (계좌번호는 마스킹 처리)",
)
async def list_accounts():
    """전체 계좌 목록 (마스킹 적용)."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT a.*, c.name, c.risk_grade
               FROM accounts a
               JOIN customers c ON a.customer_id = c.customer_id
               ORDER BY a.customer_id"""
        ).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["account_id_masked"] = mask_account_id(d["account_id"])
        result.append(d)
    return result


@router.get(
    "/{account_id}",
    summary="계좌 상세 조회",
)
async def get_account(account_id: str):
    """특정 계좌의 상세 정보 및 최근 거래 통계."""
    info = get_account_info(account_id)
    if not info:
        raise HTTPException(status_code=404, detail="계좌를 찾을 수 없습니다")

    stats_1h = get_tx_stats(account_id, hours=1)
    stats_24h = get_tx_stats(account_id, hours=24)

    return {
        "account": info,
        "account_id_masked": mask_account_id(account_id),
        "stats_1h": stats_1h,
        "stats_24h": stats_24h,
    }


@router.get(
    "/{account_id}/transactions",
    summary="계좌 거래 이력 조회",
)
async def get_account_transactions(
    account_id: str,
    hours: int = Query(24, ge=1, le=720, description="조회 기간 (시간 단위, 최대 30일)"),
    limit: int = Query(50, ge=1, le=200),
):
    """특정 계좌의 거래 이력 조회."""
    info = get_account_info(account_id)
    if not info:
        raise HTTPException(status_code=404, detail="계좌를 찾을 수 없습니다")

    transactions = get_recent_transactions(account_id, hours=hours)
    return {
        "account_id": account_id,
        "account_id_masked": mask_account_id(account_id),
        "period_hours": hours,
        "total_count": len(transactions),
        "transactions": transactions[:limit],
    }


@router.get(
    "/customers/list",
    summary="전체 고객 목록 조회",
)
async def list_customers():
    """등록된 전체 고객 목록."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM customers ORDER BY customer_id"
        ).fetchall()
    return [dict(r) for r in rows]
