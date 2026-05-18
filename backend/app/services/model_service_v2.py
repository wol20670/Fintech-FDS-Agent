"""
═══════════════════════════════════════════════════════════════
FDS 모델 추론 서비스 v2 (강화 피처 버전)
═══════════════════════════════════════════════════════════════
better_agent_v2.ipynb 로 재학습된 모델에 대응.

v1 → v2 변경사항:
  피처 4개 추가:
    balance_drain_ratio : 잔액 소진율 (0~1) ← 핵심
    orig_zero_after     : 거래 후 잔액 0 플래그
    is_large_tx         : 고액 TRANSFER/CASH_OUT 플래그
    dest_no_increase    : 수취인 잔액 미증가 (자금세탁)

  총 피처: 12개 → 16개
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


class FDSModelService:
    """FDS 모델 추론 서비스 (싱글톤)."""

    _instance: Optional[FDSModelService] = None
    _base_models = None
    _meta_model  = None
    _model_loaded: bool = False

    # PaySim LabelEncoder 결과 (학습 시와 동일해야 함)
    # CASH_IN=0, CASH_OUT=1, DEBIT=2, PAYMENT=3, TRANSFER=4
    TX_TYPE_ENCODING = {
        "CASH_IN": 0, "CASH_OUT": 1, "DEBIT": 2,
        "PAYMENT": 3, "TRANSFER": 4,
    }

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load_models(self, model_dir: str = None):
        if model_dir is None:
            model_dir = str(Path(__file__).resolve().parent.parent.parent / "models")

        base_path = Path(model_dir) / "base_models.pkl"
        meta_path = Path(model_dir) / "meta_model.pkl"

        try:
            import joblib
            if base_path.exists() and meta_path.exists():
                self._base_models = joblib.load(base_path)
                self._meta_model  = joblib.load(meta_path)
                self._model_loaded = True
                logger.info(f"[MODEL] ML 모델 로드 완료 (v2 강화 피처): {model_dir}")
            else:
                self._model_loaded = False
                logger.warning("[MODEL] 모델 파일 미발견 → Rule-Based 폴백")
        except Exception as e:
            self._model_loaded = False
            logger.error(f"[MODEL] 로드 실패: {e}")

    @property
    def is_ml_mode(self) -> bool:
        return self._model_loaded

    # ════════════════════════════════════════
    # 피처 변환 (v2: 16개 피처)
    # ════════════════════════════════════════

    def _telegram_to_features(self, telegram: TransactionTelegram) -> np.ndarray:
        """
        전문 → 피처 벡터 변환.

        better_agent_v2.ipynb 의 컬럼 순서와 정확히 일치:
        [step, amount, oldbalanceOrg, newbalanceOrig,
         oldbalanceDest, newbalanceDest, isFlaggedFraud,
         orig_is_customer, dest_is_merchant,
         balance_diff_orig, balance_diff_dest, type_enc,
         balance_drain_ratio, orig_zero_after,        ← v2 신규
         is_large_tx, dest_no_increase]               ← v2 신규
        """
        body   = telegram.body
        sender = body.sender
        recv   = body.receiver
        amount = body.amount
        eps    = 1e-9

        # ── 기존 피처 ──
        step             = 1
        old_bal_orig     = sender.current_balance
        new_bal_orig     = max(old_bal_orig - amount, 0)
        old_bal_dest     = recv.current_balance
        new_bal_dest     = old_bal_dest + amount

        is_flagged       = 1 if (
            body.transaction_type == TransactionType.TRANSFER
            and amount >= 200_000
        ) else 0

        orig_is_customer = 1 if sender.account_type == "C" else 0
        dest_is_merchant = 1 if recv.account_type   == "M" else 0

        balance_diff_orig = old_bal_orig - new_bal_orig - amount
        balance_diff_dest = new_bal_dest - old_bal_dest - amount

        type_enc = self.TX_TYPE_ENCODING.get(
            body.transaction_type.value, 4
        )

        # ── 신규 피처 (v2) ──
        # 1. 잔액 소진율: 핵심 피처 (93% 이체 = 고위험)
        balance_drain_ratio = min(amount / (old_bal_orig + eps), 1.0)

        # 2. 거래 후 잔액 0 플래그
        orig_zero_after = 1 if new_bal_orig == 0 else 0

        # 3. 고액 TRANSFER/CASH_OUT 플래그
        is_large_tx = 1 if (
            amount >= 1_000_000
            and type_enc in [1, 4]  # CASH_OUT=1, TRANSFER=4
        ) else 0

        # 4. 수취인 잔액 미증가 (자금세탁 계좌 패턴)
        dest_no_increase = 1 if (
            old_bal_dest == 0 and recv.account_type == "C"
        ) else 0

        return np.array([[
            step,                 # 0
            amount,               # 1
            old_bal_orig,         # 2: oldbalanceOrg
            new_bal_orig,         # 3: newbalanceOrig
            old_bal_dest,         # 4: oldbalanceDest
            new_bal_dest,         # 5: newbalanceDest
            is_flagged,           # 6: isFlaggedFraud
            orig_is_customer,     # 7
            dest_is_merchant,     # 8
            balance_diff_orig,    # 9
            balance_diff_dest,    # 10
            type_enc,             # 11
            balance_drain_ratio,  # 12 ← 신규
            orig_zero_after,      # 13 ← 신규
            is_large_tx,          # 14 ← 신규
            dest_no_increase,     # 15 ← 신규
        ]], dtype=np.float32)

    # ════════════════════════════════════════
    # ML 추론
    # ════════════════════════════════════════

    def _predict_ml(self, features: np.ndarray) -> float:
        xgb_m, lgbm_m = self._base_models
        p1 = xgb_m.predict_proba(features)[:, 1]
        p2 = lgbm_m.predict_proba(features)[:, 1]
        meta_in    = np.column_stack([p1, p2])
        final_prob = self._meta_model.predict_proba(meta_in)[:, 1]
        return float(final_prob[0])

    # ════════════════════════════════════════
    # Rule-Based 폴백 (v2 강화)
    # ════════════════════════════════════════

    def _predict_rule_based(self, telegram: TransactionTelegram) -> float:
        body   = telegram.body
        meta   = telegram.fds_metadata
        amount = body.amount
        bal    = body.sender.current_balance
        eps    = 1e-9
        score  = 0.0

        # 잔액 초과
        if amount > bal and bal > 0:
            score += 0.45

        # 잔액 소진율 기반 (v2 신규 규칙)
        drain = amount / (bal + eps)
        if drain >= 0.95:
            score += 0.30
        elif drain >= 0.80:
            score += 0.20
        elif drain >= 0.50:
            score += 0.10

        # 거래 유형 + 금액
        if body.transaction_type in [
            TransactionType.TRANSFER, TransactionType.CASH_OUT
        ]:
            if amount >= 1_000_000:
                score += 0.15
            if amount >= 5_000_000:
                score += 0.10

        # 수취인 유형
        if body.receiver.account_type == "C":
            score += 0.05

        # FDS 메타데이터
        if meta:
            if meta.tx_count_1h and meta.tx_count_1h >= 5:
                score += 0.15
            if meta.is_new_device:
                score += 0.10
            if meta.is_new_receiver:
                score += 0.10

        # DB 패턴
        try:
            stats_1h  = get_tx_stats(body.sender.account_id, hours=1)
            stats_24h = get_tx_stats(body.sender.account_id, hours=24)
            if stats_1h["tx_count"] >= 3:
                score += 0.10
            if stats_24h["avg_amount"] > 0 and amount > stats_24h["avg_amount"] * 3:
                score += 0.15
        except Exception:
            pass

        return min(score, 1.0)

    # ════════════════════════════════════════
    # 등급 / 대응 / XAI
    # ════════════════════════════════════════

    @staticmethod
    def _score_to_risk_level(score: float) -> RiskLevel:
        if score < 0.1:   return RiskLevel.SAFE
        elif score < 0.3: return RiskLevel.LOW
        elif score < 0.6: return RiskLevel.MEDIUM
        elif score < 0.85:return RiskLevel.HIGH
        else:             return RiskLevel.CRITICAL

    @staticmethod
    def _determine_action(risk_level: RiskLevel) -> str:
        return {
            RiskLevel.SAFE:     "APPROVE",
            RiskLevel.LOW:      "APPROVE",
            RiskLevel.MEDIUM:   "HOLD",
            RiskLevel.HIGH:     "BLOCK",
            RiskLevel.CRITICAL: "FREEZE",
        }[risk_level]

    def _generate_reason(
        self, telegram: TransactionTelegram,
        score: float, risk_level: RiskLevel
    ) -> str:
        reasons = []
        body    = telegram.body
        meta    = telegram.fds_metadata
        bal     = body.sender.current_balance
        amount  = body.amount
        eps     = 1e-9

        engine = "ML Stacking Ensemble v2" if self._model_loaded else "Rule-Based Engine v2"
        reasons.append(f"[{engine}] 리스크 점수: {score:.4f}")

        # 잔액 소진율 (v2 핵심 설명)
        drain = amount / (bal + eps)
        if drain >= 0.95:
            reasons.append(f"잔액 거의 전액 이체 (소진율 {drain*100:.1f}%)")
        elif drain >= 0.80:
            reasons.append(f"잔액 대비 고액 거래 (소진율 {drain*100:.1f}%)")

        # 잔액 초과
        if amount > bal:
            reasons.append(f"잔액 초과 거래 (잔액 ₩{bal:,.0f} < 거래액 ₩{amount:,.0f})")

        # 거래 유형
        if body.transaction_type in [
            TransactionType.TRANSFER, TransactionType.CASH_OUT
        ] and amount >= 1_000_000:
            reasons.append(f"고액 {body.transaction_type.value} 거래 (₩{amount:,.0f})")

        # 수취인 유형
        if body.receiver.account_type == "C":
            reasons.append("수취인이 개인 계좌 (가맹점 아님)")
        else:
            reasons.append("수취인이 가맹점 계좌")

        # 메타데이터
        if meta:
            if meta.is_new_device:
                reasons.append("신규 디바이스에서 접속")
            if meta.is_new_receiver:
                reasons.append("최초 거래하는 수취인")
            if meta.tx_count_1h and meta.tx_count_1h >= 3:
                reasons.append(f"최근 1시간 내 {meta.tx_count_1h}건 거래 (속도 제한 주의)")

        if len(reasons) == 1:
            reasons.append("특이사항 없음 - 정상 패턴")

        return " | ".join(reasons)

    # ════════════════════════════════════════
    # 메인 심사
    # ════════════════════════════════════════

    def evaluate_transaction(
        self, telegram: TransactionTelegram
    ) -> TransactionResponse:
        start = time.time()

        if self._model_loaded:
            features   = self._telegram_to_features(telegram)
            risk_score = self._predict_ml(features)
        else:
            risk_score = self._predict_rule_based(telegram)

        risk_level = self._score_to_risk_level(risk_score)
        action     = self._determine_action(risk_level)
        reason     = self._generate_reason(telegram, risk_score, risk_level)
        proc_ms    = (time.time() - start) * 1000

        return TransactionResponse(
            header=telegram.header,
            fds_result=FDSResult(
                risk_score=round(risk_score, 6),
                risk_level=risk_level,
                action=action,
                reason=reason,
                model_version="FDS_v2_enhanced" if self._model_loaded else "Rule_Based_v2",
                processing_time_ms=round(proc_ms, 2),
            ),
        )


# 싱글톤
fds_service = FDSModelService()