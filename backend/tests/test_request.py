"""
═══════════════════════════════════════════════════════════════
FDS API 테스트용 샘플 요청 스크립트
═══════════════════════════════════════════════════════════════
서버 실행 후 이 스크립트를 실행하면 다양한 시나리오의
거래 전문을 보내고 FDS 심사 결과를 확인할 수 있습니다.

실행 방법:
  $ python tests/test_request.py

※ 서버가 http://localhost:8000 에서 실행 중이어야 합니다.
═══════════════════════════════════════════════════════════════
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000/api/v1"


def print_result(title: str, response):
    """결과를 보기 좋게 출력."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")
    print(f"  Status: {response.status_code}")
    data = response.json()
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ════════════════════════════════════════════
# 시나리오 1: 정상 소액 이체 (SAFE 예상)
# ════════════════════════════════════════════
def test_normal_transfer():
    """정상적인 소액 이체 테스트."""
    telegram = {
        "header": {
            "telegram_no": "20260408MB0000000101",
            "channel_code": "MB",
            "terminal_id": "MOB-SAMSUNG-001",
            "institution_code": "088"
        },
        "body": {
            "transaction_type": "TRANSFER",
            "amount": 50000,
            "sender": {
                "account_id": "C1000000001",
                "account_type": "C",
                "current_balance": 1500000
            },
            "receiver": {
                "account_id": "M2000000001",
                "account_type": "M",
                "current_balance": 50000000
            }
        },
        "fds_metadata": {
            "tx_count_1h": 1,
            "tx_count_24h": 3,
            "is_new_device": False,
            "is_new_receiver": False
        }
    }
    resp = requests.post(f"{BASE_URL}/fds/evaluate", json=telegram)
    print_result("시나리오 1: 정상 소액 이체 (→ SAFE 예상)", resp)


# ════════════════════════════════════════════
# 시나리오 2: 고액 + 신규수취인 + 신규디바이스 (HIGH 예상)
# ════════════════════════════════════════════
def test_suspicious_transfer():
    """의심스러운 고액 이체 테스트."""
    telegram = {
        "header": {
            "telegram_no": "20260408IB0000000102",
            "channel_code": "IB",
            "terminal_id": "WEB-CHROME-NEW",
            "institution_code": "088"
        },
        "body": {
            "transaction_type": "TRANSFER",
            "amount": 4500000,
            "sender": {
                "account_id": "C1000000010",
                "account_type": "C",
                "current_balance": 500000
            },
            "receiver": {
                "account_id": "C1000000003",
                "account_type": "C",
                "current_balance": 850000
            }
        },
        "fds_metadata": {
            "tx_count_1h": 7,
            "tx_count_24h": 15,
            "is_new_device": True,
            "is_new_receiver": True,
            "client_ip": "103.45.67.89",
            "geo_location": "Unknown"
        }
    }
    resp = requests.post(f"{BASE_URL}/fds/evaluate", json=telegram)
    print_result("시나리오 2: 의심 고액 이체 (→ HIGH/CRITICAL 예상)", resp)


# ════════════════════════════════════════════
# 시나리오 3: 배치 분석
# ════════════════════════════════════════════
def test_batch():
    """배치 분석 테스트 (3건)."""
    batch = {
        "transactions": [
            {
                "header": {"telegram_no": f"20260408MB00000002{i:02d}", "channel_code": "MB", "terminal_id": "BATCH"},
                "body": {
                    "transaction_type": "PAYMENT",
                    "amount": 30000 * (i + 1),
                    "sender": {"account_id": "C1000000002", "account_type": "C", "current_balance": 3200000},
                    "receiver": {"account_id": "M2000000001", "account_type": "M", "current_balance": 50000000},
                }
            }
            for i in range(3)
        ]
    }
    resp = requests.post(f"{BASE_URL}/fds/batch", json=batch)
    print_result("시나리오 3: 배치 분석 (3건)", resp)


# ════════════════════════════════════════════
# 유틸리티: 서비스 상태 확인
# ════════════════════════════════════════════
def test_health():
    """서비스 상태 확인."""
    resp = requests.get(f"{BASE_URL}/fds/health")
    print_result("FDS 서비스 상태", resp)


def test_accounts():
    """계좌 목록 조회."""
    resp = requests.get(f"{BASE_URL}/accounts/")
    print_result("계좌 목록", resp)


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  FDS Agent API 테스트 시작")
    print("=" * 60)

    test_health()
    test_normal_transfer()
    test_suspicious_transfer()
    test_batch()
    test_accounts()

    print("\n\n테스트 완료!")
