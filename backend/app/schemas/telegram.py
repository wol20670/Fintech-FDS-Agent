"""
═══════════════════════════════════════════════════════════════
금융 데이터 전문(Telegram) 스키마 정의
═══════════════════════════════════════════════════════════════
실제 은행 전문 구조를 JSON 기반으로 간소화하여 설계.
전문은 크게 3개 영역으로 구성:
  - Header : 거래 식별 및 라우팅 정보 (은행 공통 헤더)
  - Body   : 실제 거래 데이터 (송금인/수취인/금액 등)
  - FDS Metadata : 모델 판단에 필요한 파생 피처 및 부가 정보

※ 금융보안원 가이드라인에 따라 개인정보(계좌번호 등)는
   마스킹 처리된 형태로 응답에 포함됩니다.
═══════════════════════════════════════════════════════════════
"""

from __future__ import annotations
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal
from datetime import datetime
from enum import Enum


# ────────────────────────────────────────────
# 공통 Enum 정의
# ────────────────────────────────────────────

class ChannelCode(str, Enum):
    """
    거래가 발생한 채널을 식별하는 코드.
    실제 은행에서는 각 채널별로 리스크 가중치가 다르게 적용됨.
    예: 모바일 > 인터넷뱅킹 > ATM 순으로 사기 위험도가 높은 경향.
    """
    MOBILE = "MB"       # 모바일뱅킹
    INTERNET = "IB"     # 인터넷뱅킹
    ATM = "AT"          # ATM
    TELLER = "TL"       # 창구(텔러)
    OPEN_BANKING = "OB" # 오픈뱅킹 API


class TransactionType(str, Enum):
    """
    PaySim 데이터셋의 거래 유형과 매핑.
    실제 은행 전문에서도 '거래구분코드'로 유사하게 사용됨.
    """
    CASH_IN = "CASH_IN"
    CASH_OUT = "CASH_OUT"
    DEBIT = "DEBIT"
    PAYMENT = "PAYMENT"
    TRANSFER = "TRANSFER"


class RiskLevel(str, Enum):
    """FDS 판단 결과의 위험 등급 (4단계)."""
    SAFE = "SAFE"           # 정상 - 자동 승인
    LOW = "LOW"             # 주의 - 승인하되 로그 강화
    MEDIUM = "MEDIUM"       # 경고 - 추가 인증 요구 (SMS/ARS 등)
    HIGH = "HIGH"           # 위험 - 즉시 차단 및 관리자 알림
    CRITICAL = "CRITICAL"   # 긴급 - 계좌 동결 + 수사 의뢰 대상


# ────────────────────────────────────────────
# 전문 Header (공통 헤더)
# ────────────────────────────────────────────

class TelegramHeader(BaseModel):
    """
    은행 전문 공통 헤더.
    모든 거래 요청/응답에 반드시 포함되는 식별 정보.
    실제 은행에서는 전문번호로 거래를 추적하고,
    채널코드로 리스크 가중치를 다르게 적용합니다.
    """

    # 전문번호: 거래를 고유하게 식별하는 20자리 번호
    # 형식: YYYYMMDD + 채널코드(2) + 일련번호(10)
    telegram_no: str = Field(
        ...,
        min_length=10,
        max_length=30,
        description="전문번호 (거래 고유 식별자)",
        examples=["20260408MB0000000001"]
    )

    # 거래 일시 (ISO 8601 형식)
    transaction_dt: datetime = Field(
        default_factory=datetime.now,
        description="거래 발생 일시 (KST 기준)"
    )

    # 채널 코드
    channel_code: ChannelCode = Field(
        ...,
        description="거래 채널 (MB: 모바일, IB: 인터넷뱅킹 등)"
    )

    # 단말기 번호: 거래가 발생한 디바이스/단말 식별
    terminal_id: str = Field(
        default="UNKNOWN",
        max_length=20,
        description="단말기/디바이스 식별 번호"
    )

    # 기관 코드: 거래를 요청한 금융기관 식별
    institution_code: str = Field(
        default="088",  # 기본값: 신한은행 코드 (예시)
        max_length=4,
        description="금융기관 코드 (예: 088=신한, 004=KB국민)"
    )


# ────────────────────────────────────────────
# 전문 Body (거래 데이터 본문)
# ────────────────────────────────────────────

class SenderInfo(BaseModel):
    """
    송금인(출금자) 정보.
    개인정보보호법에 따라 계좌번호는 마스킹 처리하여 로그에 남기며,
    내부 처리 시에만 원본 데이터를 사용합니다.
    """
    account_id: str = Field(
        ...,
        description="송금인 계좌 식별자 (내부용, PaySim의 nameOrig에 대응)"
    )
    account_type: Literal["C", "M"] = Field(
        default="C",
        description="계좌 유형 (C: 개인고객, M: 가맹점/법인)"
    )
    current_balance: float = Field(
        ...,
        ge=0,
        description="거래 전 현재 잔액 (PaySim의 oldbalanceOrg에 대응)"
    )


class ReceiverInfo(BaseModel):
    """
    수취인(입금 대상) 정보.
    타행 이체 시 기관 코드가 추가로 필요하며,
    가맹점 계좌인 경우 사기 확률이 낮은 것이 일반적 패턴임.
    """
    account_id: str = Field(
        ...,
        description="수취인 계좌 식별자 (내부용, PaySim의 nameDest에 대응)"
    )
    account_type: Literal["C", "M"] = Field(
        default="C",
        description="계좌 유형 (C: 개인고객, M: 가맹점/법인)"
    )
    current_balance: float = Field(
        ...,
        ge=0,
        description="수취 계좌의 거래 전 잔액 (PaySim의 oldbalanceDest에 대응)"
    )
    institution_code: Optional[str] = Field(
        default=None,
        description="수취 기관 코드 (타행이체 시 필수)"
    )


class TelegramBody(BaseModel):
    """
    거래 전문 본문.
    실제 은행 전문에서는 이 영역에 거래금액, 수수료,
    통화코드, 적요(메모) 등이 포함됩니다.
    """

    transaction_type: TransactionType = Field(
        ...,
        description="거래 유형 (PaySim의 type 필드와 매핑)"
    )

    amount: float = Field(
        ...,
        gt=0,
        description="거래 금액 (0보다 커야 함)"
    )

    sender: SenderInfo = Field(
        ...,
        description="송금인(출금) 정보"
    )

    receiver: ReceiverInfo = Field(
        ...,
        description="수취인(입금) 정보"
    )

    currency: str = Field(
        default="KRW",
        max_length=3,
        description="통화 코드 (ISO 4217)"
    )

    memo: Optional[str] = Field(
        default=None,
        max_length=100,
        description="거래 적요/메모"
    )


# ────────────────────────────────────────────
# FDS Metadata (사기탐지 부가 정보)
# ────────────────────────────────────────────

class FDSMetadata(BaseModel):
    """
    FDS 판단에 필요한 파생 피처 및 부가 정보.

    이 영역은 클라이언트가 직접 채워서 보낼 수도 있고,
    서버 측에서 DB 조회 후 자동 계산할 수도 있음.

    ※ 실제 은행 FDS에서는 이 파생 피처들이 실시간으로
      계산되며, 고객의 과거 행동 패턴과 비교 분석됩니다.
    """

    # 최근 N시간 내 거래 횟수 (속도 기반 탐지)
    tx_count_1h: Optional[int] = Field(
        default=0,
        ge=0,
        description="최근 1시간 내 동일 계좌의 거래 횟수"
    )

    tx_count_24h: Optional[int] = Field(
        default=0,
        ge=0,
        description="최근 24시간 내 동일 계좌의 거래 횟수"
    )

    # 최근 거래 금액 합계 (누적 한도 체크)
    tx_amount_sum_1h: Optional[float] = Field(
        default=0.0,
        ge=0,
        description="최근 1시간 내 거래 금액 합계"
    )

    tx_amount_sum_24h: Optional[float] = Field(
        default=0.0,
        ge=0,
        description="최근 24시간 내 거래 금액 합계"
    )

    # 평균 거래 금액 대비 현재 거래의 편차
    avg_tx_amount: Optional[float] = Field(
        default=0.0,
        ge=0,
        description="해당 계좌의 평균 거래 금액 (과거 패턴 기준)"
    )

    # IP/위치 정보 (이상 접속 탐지)
    client_ip: Optional[str] = Field(
        default=None,
        description="거래 요청 IP 주소"
    )

    geo_location: Optional[str] = Field(
        default=None,
        description="접속 위치 (도시 단위, 예: 'Seoul', 'Busan')"
    )

    # 디바이스 핑거프린트 (기기 변경 탐지)
    device_fingerprint: Optional[str] = Field(
        default=None,
        description="디바이스 고유 식별 해시값"
    )

    is_new_device: Optional[bool] = Field(
        default=False,
        description="최초 접속 디바이스 여부 (True면 리스크 가중)"
    )

    is_new_receiver: Optional[bool] = Field(
        default=False,
        description="처음 거래하는 수취인 여부"
    )


# ────────────────────────────────────────────
# 완성된 거래 전문 (Request)
# ────────────────────────────────────────────

class TransactionTelegram(BaseModel):
    """
    최종 거래 전문 (요청).

    은행 시스템에서 FDS로 전달되는 하나의 완전한 전문 단위.
    Header + Body + FDS Metadata 의 3개 영역으로 구성됩니다.

    사용 예시:
    ```json
    {
      "header": {
        "telegram_no": "20260408MB0000000001",
        "channel_code": "MB",
        "terminal_id": "MOB-SAMSUNG-001"
      },
      "body": {
        "transaction_type": "TRANSFER",
        "amount": 500000.0,
        "sender": {
          "account_id": "C1234567890",
          "account_type": "C",
          "current_balance": 1200000.0
        },
        "receiver": {
          "account_id": "C0987654321",
          "account_type": "C",
          "current_balance": 50000.0
        }
      },
      "fds_metadata": {
        "tx_count_1h": 3,
        "tx_count_24h": 8,
        "is_new_receiver": true
      }
    }
    ```
    """
    header: TelegramHeader
    body: TelegramBody
    fds_metadata: Optional[FDSMetadata] = Field(
        default_factory=FDSMetadata,
        description="FDS 부가 정보 (미입력 시 서버가 DB에서 자동 조회)"
    )


# ────────────────────────────────────────────
# FDS 심사 결과 전문 (Response)
# ────────────────────────────────────────────

class FDSResult(BaseModel):
    """
    FDS 심사 결과.

    실제 은행에서는 이 결과를 기반으로:
    - SAFE/LOW  → 거래 자동 승인
    - MEDIUM    → 추가 인증(SMS/ARS) 후 승인
    - HIGH      → 즉시 차단 + 고객 연락
    - CRITICAL  → 계좌 동결 + 금융감독원 보고
    """
    risk_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="사기 확률 점수 (0.0=정상 ~ 1.0=확실한 사기)"
    )

    risk_level: RiskLevel = Field(
        ...,
        description="위험 등급 (SAFE/LOW/MEDIUM/HIGH/CRITICAL)"
    )

    action: str = Field(
        ...,
        description="자율 대응 조치 (APPROVE/HOLD/BLOCK/FREEZE)"
    )

    reason: str = Field(
        ...,
        description="판단 근거 설명 (XAI - 설명 가능한 AI)"
    )

    model_version: str = Field(
        default="FDS_Robust_Model_v1",
        description="판단에 사용된 모델 버전"
    )

    processing_time_ms: float = Field(
        ...,
        ge=0,
        description="심사 처리 소요 시간 (밀리초)"
    )

    shap_values: Optional[dict] = Field(
    default=None,
    description="SHAP 피처 기여도 (XAI)"
    )


class TransactionResponse(BaseModel):
    """
    거래 심사 응답 전문.
    요청 헤더를 그대로 반환하여 전문 추적이 가능하도록 함.
    """
    header: TelegramHeader = Field(
        ...,
        description="요청 전문의 헤더를 그대로 반환 (추적용)"
    )
    fds_result: FDSResult = Field(
        ...,
        description="FDS 심사 결과"
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="응답 생성 시각"
    )


# ────────────────────────────────────────────
# 배치 분석용 스키마
# ────────────────────────────────────────────

class BatchAnalysisRequest(BaseModel):
    """배치(다건) 거래 분석 요청."""
    transactions: list[TransactionTelegram] = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="분석할 거래 전문 목록 (최대 10,000건)"
    )


class BatchAnalysisResponse(BaseModel):
    """배치 분석 결과."""
    total_count: int = Field(..., description="전체 분석 건수")
    fraud_count: int = Field(..., description="사기 의심 건수")
    safe_count: int = Field(..., description="정상 판정 건수")
    results: list[TransactionResponse] = Field(
        ...,
        description="건별 심사 결과 목록"
    )
    processing_time_ms: float = Field(
        ...,
        description="전체 배치 처리 소요 시간 (밀리초)"
    )


# ────────────────────────────────────────────
# 개인정보 마스킹 유틸리티
# ────────────────────────────────────────────

def mask_account_id(account_id: str) -> str:
    """
    계좌번호 마스킹 처리.

    금융보안원 개인정보보호 가이드라인에 따라
    계좌번호의 앞 3자리와 마지막 2자리만 노출하고
    나머지는 '*'로 처리합니다.

    예: "C1234567890" → "C12*****90"
    """
    if len(account_id) <= 5:
        return account_id[:2] + "*" * (len(account_id) - 2)
    return account_id[:3] + "*" * (len(account_id) - 5) + account_id[-2:]
