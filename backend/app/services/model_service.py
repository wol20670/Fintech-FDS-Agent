"""
═══════════════════════════════════════════════════════════════
FDS 모델 추론 서비스 (Model Inference Service)
═══════════════════════════════════════════════════════════════
Colab에서 학습한 Stacking Ensemble 모델을 로드하여
실시간 사기 탐지 추론을 수행하는 모듈.

아키텍처:
  1. 전문(Telegram) → 피처 변환 (Feature Engineering)
  2. XGBoost + LightGBM → 각각 사기 확률 예측
  3. Meta Model (Logistic Regression) → 최종 사기 확률 산출
  4. 리스크 점수 → 위험 등급 매핑 → 자율 대응 결정

※ 모델 파일(.pkl)이 없는 경우, 규칙 기반(Rule-Based) 엔진으로
   폴백하여 서비스가 중단되지 않도록 설계했습니다.
   캡스톤 데모 시 모델 파일 없이도 테스트 가능합니다.
═══════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import time
import logging
from pathlib import Path
from typing import Optional

import numpy as np

from app.schemas.telegram import (
    TransactionTelegram, FDSResult, TransactionResponse,
    RiskLevel, TransactionType, mask_account_id
)
from app.models.database import get_tx_stats, get_account_info

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════
# 모델 로더 (Singleton Pattern)
# ════════════════════════════════════════════

class FDSModelService:
    """
    FDS 모델 추론 서비스.

    싱글톤 패턴으로 구현하여 모델을 한 번만 로드하고,
    모든 요청에서 재사용합니다.
    실제 운영에서는 모델 Hot-Swap(무중단 교체)을 지원해야 합니다.
    """

    _instance: Optional[FDSModelService] = None
    _base_models = None       # (XGBoost, LightGBM) 튜플
    _meta_model = None        # Logistic Regression (스태킹 메타 모델)
    _model_loaded: bool = False

    # 거래 유형 → 인코딩 매핑 (Colab의 LabelEncoder 결과와 동일해야 함)
    # PaySim 데이터의 type을 LabelEncoder로 변환한 결과:
    # CASH_IN=0, CASH_OUT=1, DEBIT=2, PAYMENT=3, TRANSFER=4
    TX_TYPE_ENCODING = {
        "CASH_IN": 0,
        "CASH_OUT": 1,
        "DEBIT": 2,
        "PAYMENT": 3,
        "TRANSFER": 4,
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_models(self, model_dir: str = None):
        """
        학습된 모델 파일 로드.

        Colab에서 저장한 파일:
          - base_models.pkl : (XGBClassifier, LGBMClassifier) 튜플
          - meta_model.pkl  : LogisticRegression 메타 모델

        ※ 파일이 없으면 규칙 기반 엔진으로 자동 전환됩니다.
        """
        if model_dir is None:
            model_dir = str(Path(__file__).resolve().parent.parent.parent / "models")

        base_path = Path(model_dir) / "base_models.pkl"
        meta_path = Path(model_dir) / "meta_model.pkl"

        try:
            import joblib
            if base_path.exists() and meta_path.exists():
                self._base_models = joblib.load(base_path)
                self._meta_model = joblib.load(meta_path)
                self._model_loaded = True
                logger.info(f"[MODEL] ML 모델 로드 완료: {model_dir}")
            else:
                self._model_loaded = False
                logger.warning(
                    f"[MODEL] 모델 파일 미발견 → 규칙 기반(Rule-Based) 엔진으로 전환\n"
                    f"        base_models.pkl: {'존재' if base_path.exists() else '미존재'}\n"
                    f"        meta_model.pkl:  {'존재' if meta_path.exists() else '미존재'}"
                )
        except Exception as e:
            self._model_loaded = False
            logger.error(f"[MODEL] 모델 로드 실패: {e} → 규칙 기반 엔진으로 전환")

    @property
    def is_ml_mode(self) -> bool:
        """ML 모델이 로드되었는지 여부."""
        return self._model_loaded

    # ════════════════════════════════════════
    # 피처 변환 (Telegram → 모델 입력 벡터)
    # ════════════════════════════════════════

    def _telegram_to_features(self, telegram: TransactionTelegram) -> np.ndarray:
        """
        전문 데이터를 모델 입력 피처 벡터로 변환.

        Colab 노트북의 피처 순서와 정확히 일치해야 합니다:
        [step, amount, oldbalanceOrg, newbalanceOrig,
         oldbalanceDest, newbalanceDest, isFlaggedFraud,
         orig_is_customer, dest_is_merchant,
         balance_diff_orig, balance_diff_dest, type_enc]
        """
        body = telegram.body
        sender = body.sender
        receiver = body.receiver
        amount = body.amount

        # ── 기본 피처 ──
        step = 1  # 실시간 거래는 현재 시점 (시뮬레이션에서는 step 활용)

        old_balance_orig = sender.current_balance
        new_balance_orig = sender.current_balance - amount  # 거래 후 잔액 추정

        old_balance_dest = receiver.current_balance
        new_balance_dest = receiver.current_balance + amount

        # isFlaggedFraud: 200,000 이상의 TRANSFER만 플래그
        # (PaySim의 isFlaggedFraud 로직 재현)
        is_flagged = 1 if (
            body.transaction_type == TransactionType.TRANSFER
            and amount >= 200_000
        ) else 0

        # ── 파생 피처 (Feature Engineering - Colab과 동일) ──
        orig_is_customer = 1 if sender.account_type == "C" else 0
        dest_is_merchant = 1 if receiver.account_type == "M" else 0

        # 잔액 불일치 탐지: 실제 줄어든 금액 vs 거래 금액
        balance_diff_orig = old_balance_orig - new_balance_orig - amount
        balance_diff_dest = new_balance_dest - old_balance_dest - amount

        # 거래 유형 인코딩
        type_enc = self.TX_TYPE_ENCODING.get(body.transaction_type.value, 4)

        # 피처 벡터 구성 (Colab 모델의 입력 순서와 동일)
        features = np.array([[
            step,               # 0: step
            amount,             # 1: amount
            old_balance_orig,   # 2: oldbalanceOrg
            new_balance_orig,   # 3: newbalanceOrig
            old_balance_dest,   # 4: oldbalanceDest
            new_balance_dest,   # 5: newbalanceDest
            is_flagged,         # 6: isFlaggedFraud
            orig_is_customer,   # 7: orig_is_customer
            dest_is_merchant,   # 8: dest_is_merchant
            balance_diff_orig,  # 9: balance_diff_orig
            balance_diff_dest,  # 10: balance_diff_dest
            type_enc,           # 11: type_enc
        ]], dtype=np.float32)

        return features

    # ════════════════════════════════════════
    # ML 기반 추론
    # ════════════════════════════════════════

    def _predict_ml(self, features: np.ndarray) -> float:
        """
        Stacking Ensemble 모델로 사기 확률 예측.

        흐름:
          1. XGBoost → 사기 확률 P1
          2. LightGBM → 사기 확률 P2
          3. Meta Model (LogisticRegression) → 최종 확률
        """
        xgb_model, lgbm_model = self._base_models

        p1 = xgb_model.predict_proba(features)[:, 1]   # XGBoost 확률
        p2 = lgbm_model.predict_proba(features)[:, 1]   # LightGBM 확률

        # 메타 모델 입력: 두 base learner의 확률을 결합
        meta_features = np.column_stack([p1, p2])
        final_proba = self._meta_model.predict_proba(meta_features)[:, 1]

        return float(final_proba[0])

    # ════════════════════════════════════════
    # 규칙 기반 폴백 엔진
    # ════════════════════════════════════════

    def _predict_rule_based(self, telegram: TransactionTelegram) -> float:
        """
        규칙 기반(Rule-Based) 사기 탐지 엔진.

        ML 모델이 없을 때 사용하는 폴백 로직.
        실제 은행 FDS에서도 ML + Rule-Based를 병행하며,
        규칙 엔진은 '1선 방어'로 활용됩니다.

        규칙 목록:
          R1. 잔액 초과 거래 → 고위험
          R2. 고액 이체 (잔액의 80% 이상) → 중위험
          R3. 신규 수취인 + 고액 → 중위험
          R4. 새 디바이스 + 고액 → 중위험
          R5. 단시간 다수 거래 → 위험 가중
        """
        body = telegram.body
        meta = telegram.fds_metadata
        risk_score = 0.0

        amount = body.amount
        sender_balance = body.sender.current_balance

        # R1: 잔액 초과 (무조건 의심)
        if amount > sender_balance and sender_balance > 0:
            risk_score += 0.4

        # R2: 잔액 대비 고액 이체 (80% 이상)
        if sender_balance > 0 and (amount / sender_balance) >= 0.8:
            risk_score += 0.25

        # R3: TRANSFER/CASH_OUT이면서 고액
        if body.transaction_type in [TransactionType.TRANSFER, TransactionType.CASH_OUT]:
            if amount >= 1_000_000:
                risk_score += 0.15
            if amount >= 5_000_000:
                risk_score += 0.1

        # R4: 수취인이 개인 계좌 (가맹점이 아닌 경우 리스크 가중)
        if body.receiver.account_type == "C":
            risk_score += 0.05

        # R5: FDS Metadata 기반 가중
        if meta:
            # 최근 1시간 내 5건 이상 거래 → 속도 제한(Velocity Check)
            if meta.tx_count_1h and meta.tx_count_1h >= 5:
                risk_score += 0.15
            # 신규 디바이스
            if meta.is_new_device:
                risk_score += 0.1
            # 신규 수취인
            if meta.is_new_receiver:
                risk_score += 0.1

        # DB에서 과거 거래 패턴 조회하여 추가 판단
        try:
            stats_1h = get_tx_stats(body.sender.account_id, hours=1)
            stats_24h = get_tx_stats(body.sender.account_id, hours=24)

            # 최근 1시간 거래가 많으면 가중
            if stats_1h["tx_count"] >= 3:
                risk_score += 0.1

            # 평균 거래 금액 대비 3배 이상이면 이상 거래
            if stats_24h["avg_amount"] > 0 and amount > stats_24h["avg_amount"] * 3:
                risk_score += 0.15
        except Exception:
            pass  # DB 조회 실패 시 무시 (규칙만으로 판단)

        return min(risk_score, 1.0)  # 최대 1.0으로 클리핑

    # ════════════════════════════════════════
    # 리스크 등급 매핑 및 자율 대응
    # ════════════════════════════════════════

    @staticmethod
    def _score_to_risk_level(score: float) -> RiskLevel:
        """
        사기 확률 점수 → 위험 등급 매핑.

        임계값은 은행 리스크 관리 정책에 따라 조정 가능.
        실제 운영에서는 이 임계값을 DB/Config로 관리하여
        모델 재배포 없이 정책을 변경할 수 있도록 합니다.
        """
        if score < 0.1:
            return RiskLevel.SAFE
        elif score < 0.3:
            return RiskLevel.LOW
        elif score < 0.6:
            return RiskLevel.MEDIUM
        elif score < 0.85:
            return RiskLevel.HIGH
        else:
            return RiskLevel.CRITICAL

    @staticmethod
    def _determine_action(risk_level: RiskLevel) -> str:
        """
        위험 등급 → 자율 대응 조치 결정.

        은행 내부 정책:
        - APPROVE : 정상 승인, 거래 진행
        - HOLD    : 추가 인증 후 승인 (SMS/ARS)
        - BLOCK   : 거래 차단, 고객에게 통보
        - FREEZE  : 계좌 동결 + 금감원 보고
        """
        action_map = {
            RiskLevel.SAFE:     "APPROVE",
            RiskLevel.LOW:      "APPROVE",      # 승인하되 모니터링 로그 강화
            RiskLevel.MEDIUM:   "HOLD",         # 추가 인증 요구
            RiskLevel.HIGH:     "BLOCK",        # 즉시 차단
            RiskLevel.CRITICAL: "FREEZE",       # 계좌 동결
        }
        return action_map[risk_level]

    def _generate_reason(
        self, telegram: TransactionTelegram, score: float, risk_level: RiskLevel
    ) -> str:
        """
        XAI (설명 가능한 AI) - 판단 근거 생성.

        사용자와 감사인이 모델의 판단 이유를 이해할 수 있도록
        자연어로 설명을 생성합니다.
        실제 운영에서는 SHAP/LIME 등의 XAI 라이브러리를 활용.
        """
        reasons = []
        body = telegram.body
        meta = telegram.fds_metadata

        # 모델 유형 명시
        engine = "ML Stacking Ensemble" if self._model_loaded else "Rule-Based Engine"
        reasons.append(f"[{engine}] 리스크 점수: {score:.4f}")

        # 주요 판단 요인 설명
        if body.amount > body.sender.current_balance * 0.8:
            reasons.append("잔액 대비 고액 거래 감지")

        if body.transaction_type in [TransactionType.TRANSFER, TransactionType.CASH_OUT]:
            if body.amount >= 1_000_000:
                reasons.append(f"고액 {body.transaction_type.value} 거래 (₩{body.amount:,.0f})")

        if body.receiver.account_type == "C":
            reasons.append("수취인이 개인 계좌 (가맹점 아님)")

        if meta:
            if meta.is_new_device:
                reasons.append("신규 디바이스에서 접속")
            if meta.is_new_receiver:
                reasons.append("최초 거래하는 수취인")
            if meta.tx_count_1h and meta.tx_count_1h >= 3:
                reasons.append(f"최근 1시간 내 {meta.tx_count_1h}건 거래 (속도 제한 주의)")

        if not reasons[1:]:
            reasons.append("특이사항 없음 - 정상 패턴")

        return " | ".join(reasons)

    # ════════════════════════════════════════
    # 메인 심사 함수 (Public API)
    # ════════════════════════════════════════

    def evaluate_transaction(self, telegram: TransactionTelegram) -> TransactionResponse:
        """
        단건 거래 FDS 심사.

        전체 흐름:
          1. 전문 → 피처 벡터 변환
          2. ML 또는 Rule-Based로 사기 확률 예측
          3. 리스크 등급 및 자율 대응 결정
          4. XAI 판단 근거 생성
          5. 결과 전문 반환
        """
        start_time = time.time()

        # 1~2. 사기 확률 예측
        if self._model_loaded:
            features = self._telegram_to_features(telegram)
            risk_score = self._predict_ml(features)
        else:
            risk_score = self._predict_rule_based(telegram)

        # 3. 위험 등급 및 대응 결정
        risk_level = self._score_to_risk_level(risk_score)
        action = self._determine_action(risk_level)

        # 4. XAI 설명 생성
        reason = self._generate_reason(telegram, risk_score, risk_level)

        # 처리 시간 계산 (밀리초)
        processing_time = (time.time() - start_time) * 1000

        # 5. 응답 전문 생성
        fds_result = FDSResult(
            risk_score=round(risk_score, 6),
            risk_level=risk_level,
            action=action,
            reason=reason,
            model_version="FDS_Robust_Model_v1" if self._model_loaded else "Rule_Based_v1",
            processing_time_ms=round(processing_time, 2),
        )

        return TransactionResponse(
            header=telegram.header,
            fds_result=fds_result,
        )


# ────────────────────────────────────────────
# 서비스 인스턴스 (싱글톤)
# ────────────────────────────────────────────
fds_service = FDSModelService()
