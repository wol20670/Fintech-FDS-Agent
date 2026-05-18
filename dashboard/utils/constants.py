"""
공통 상수 및 더미 데이터 정의
- API 주소, 계좌 목록, 시나리오, 색상 매핑 등
- 변경이 필요한 값은 여기서만 수정하면 됩니다

[PaySim 모델 특성 메모]
PaySim 학습 데이터에서 사기 거래는 아래 조건에서만 발생합니다:
  - 거래 유형: TRANSFER 또는 CASH_OUT 만 해당
  - 수취인 유형: 반드시 개인 계좌(C)여야 높은 위험도 판정
  - 가맹점(M) 수취 거래는 학습 데이터에 사기가 없어 항상 SAFE 판정
따라서 고위험 시나리오는 수취인을 개인 계좌(C)로 설정해야 합니다.
"""

API_BASE = "http://localhost:8000/api/v1"

# ── 더미 계좌 (DB seed 데이터와 동일하게 유지) ──
ACCOUNTS = {
    "C1000000001": {"name": "김*현", "grade": "NORMAL",  "balance": 1_500_000,  "type": "C"},
    "C1000000002": {"name": "이*수", "grade": "NORMAL",  "balance": 2_300_000,  "type": "C"},
    "C1000000003": {"name": "박*진", "grade": "NORMAL",  "balance": 870_000,    "type": "C"},
    "C1000000004": {"name": "최*미", "grade": "NORMAL",  "balance": 5_100_000,  "type": "C"},
    "C1000000005": {"name": "정*호", "grade": "NORMAL",  "balance": 320_000,    "type": "C"},
    "C1000000008": {"name": "한*석", "grade": "CAUTION", "balance": 9_800_000,  "type": "C"},
    "C1000000009": {"name": "서*영", "grade": "CAUTION", "balance": 4_500_000,  "type": "C"},
    "C1000000010": {"name": "임*우", "grade": "HIGH",    "balance": 15_000_000, "type": "C"},
    "M2000000001": {"name": "대형마트A",   "grade": "NORMAL", "balance": 50_000_000, "type": "M"},
    "M2000000002": {"name": "온라인쇼핑B", "grade": "NORMAL", "balance": 30_000_000, "type": "M"},
}

# ── 빠른 시나리오 ──
# [PaySim 주의사항]
# ML 모델이 사기로 학습한 패턴: TRANSFER/CASH_OUT + 수취인 개인(C) + 잔액 전액 이체
# 가맹점(M) 수취 거래는 PaySim에서 사기가 없어 항상 낮은 위험도로 판정됨
SCENARIOS = [
    {
        "label": "🟢 정상 소액 이체",
        "desc":  "김*현 → 대형마트A / 50,000원",
        "params": dict(
            sender="C1000000001", receiver="M2000000001",
            tx_type="TRANSFER", amount=50_000,
            channel="MB", new_device=False, new_receiver=False, cnt_1h=1,
        ),
    },
    {
        "label": "🟡 잔액 대비 고액 이체",
        "desc":  "정*호 → 대형마트A / 275,000원 (잔액 86%)",
        "params": dict(
            sender="C1000000005", receiver="M2000000001",
            tx_type="TRANSFER", amount=275_000,
            channel="IB", new_device=False, new_receiver=False, cnt_1h=2,
        ),
    },
    {
        "label": "🟠 신규기기 + 신규수취인 고액",
        "desc":  "한*석 → 이*수 / 8,000,000원 (개인→개인, 신규)",
        # 수취인을 개인 계좌(C)로 설정 → PaySim 사기 패턴과 일치
        "params": dict(
            sender="C1000000008", receiver="C1000000002",
            tx_type="CASH_OUT", amount=8_000_000,
            channel="MB", new_device=True, new_receiver=True, cnt_1h=5,
        ),
    },
    {
        "label": "🔴 고위험 계좌 대량 이체",
        "desc":  "임*우 → 박*진 / 14,000,000원 (잔액 전액)",
        # 수취인을 개인 계좌(C)로 설정 → 잔액 거의 전액 개인 이체 = 핵심 사기 패턴
        "params": dict(
            sender="C1000000010", receiver="C1000000003",
            tx_type="TRANSFER", amount=14_000_000,
            channel="IB", new_device=True, new_receiver=True, cnt_1h=8,
        ),
    },
    {
        "label": "🚨 잔액 초과 거래",
        "desc":  "박*진 → 김*현 / 2,000,000원 (잔액 870,000원)",
        # 잔액 초과 + 개인→개인 = CRITICAL 패턴
        "params": dict(
            sender="C1000000003", receiver="C1000000001",
            tx_type="TRANSFER", amount=2_000_000,
            channel="AT", new_device=False, new_receiver=False, cnt_1h=1,
        ),
    },
]

# ── 표시용 매핑 ──
GRADE_EMOJI = {"NORMAL": "🟢", "CAUTION": "🟡", "HIGH": "🔴"}
GRADE_KO    = {"NORMAL": "정상", "CAUTION": "주의", "HIGH": "고위험"}

RISK_COLOR = {
    "SAFE":     "#22c55e",
    "LOW":      "#84cc16",
    "MEDIUM":   "#f59e0b",
    "HIGH":     "#f97316",
    "CRITICAL": "#ef4444",
}
RISK_EMOJI = {
    "SAFE": "✅", "LOW": "🟡", "MEDIUM": "🟠", "HIGH": "🔴", "CRITICAL": "🚨",
}
ACTION_KO = {
    "APPROVE":         "✅ 승인",
    "ADDITIONAL_AUTH": "⚠️ 추가인증 요청",
    "HOLD":            "⚠️ 추가인증 요청",
    "BLOCK":           "🚫 거래 차단",
    "FREEZE":          "🔒 계좌 동결",
}