"""
API 클라이언트
- FastAPI 백엔드와의 모든 HTTP 통신을 담당
- 다른 모듈은 이 파일의 함수만 호출하면 됨
"""

import time
import requests
from .constants import API_BASE


def check_server() -> tuple[bool, dict]:
    """서버 연결 상태 및 health 정보 반환."""
    try:
        r = requests.get(f"{API_BASE}/fds/health", timeout=2)
        if r.status_code == 200:
            return True, r.json()
        return False, {}
    except Exception:
        return False, {}


def call_evaluate(payload: dict) -> tuple[dict | None, int, str | None]:
    """
    단건 FDS 심사 API 호출.
    Returns: (result, elapsed_ms, error_message)
    """
    t0 = time.time()
    try:
        resp = requests.post(f"{API_BASE}/fds/evaluate", json=payload, timeout=5)
        ms   = round((time.time() - t0) * 1000)
        if resp.status_code == 200:
            return resp.json(), ms, None
        return None, ms, f"HTTP {resp.status_code}: {resp.text}"
    except Exception as e:
        return None, round((time.time() - t0) * 1000), str(e)


def fetch_fds_logs(risk_level: str = None, limit: int = 100) -> list[dict]:
    """서버 DB에서 FDS 심사 이력 조회."""
    try:
        params = {"limit": limit}
        if risk_level:
            params["risk_level"] = risk_level
        r = requests.get(f"{API_BASE}/fds/logs", params=params, timeout=3)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []


def fetch_fds_stats() -> dict | None:
    """FDS 통계 데이터 조회."""
    try:
        r = requests.get(f"{API_BASE}/fds/stats", timeout=3)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def fetch_accounts() -> list[dict]:
    """전체 계좌 목록 조회."""
    try:
        r = requests.get(f"{API_BASE}/accounts/", timeout=3)
        return r.json() if r.status_code == 200 else []
    except Exception:
        return []