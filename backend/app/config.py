"""
═══════════════════════════════════════════════════════════════
서버 설정 (Configuration)
═══════════════════════════════════════════════════════════════
환경 변수 기반 설정 관리.
.env 파일 또는 시스템 환경 변수로 오버라이드 가능.

※ 실제 운영에서는 HashiCorp Vault 등 Secret Manager를 사용하여
   민감 정보(DB 접속 정보 등)를 안전하게 관리합니다.
═══════════════════════════════════════════════════════════════
"""

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    """서버 설정."""

    # ── 서버 기본 설정 ──
    APP_NAME: str = "Fintech FDS Agent API"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True

    # ── 모델 경로 ──
    MODEL_DIR: str = str(Path(__file__).resolve().parent.parent / "models")

    # ── FDS 정책 임계값 ──
    # 이 값들을 조정하여 모델 재배포 없이 FDS 민감도를 변경할 수 있음
    RISK_THRESHOLD_LOW: float = 0.1
    RISK_THRESHOLD_MEDIUM: float = 0.3
    RISK_THRESHOLD_HIGH: float = 0.6
    RISK_THRESHOLD_CRITICAL: float = 0.85

    # ── CORS 설정 (Streamlit 대시보드 연동용) ──
    CORS_ORIGINS: list[str] = [
        "http://localhost:8501",    # Streamlit 기본 포트
        "http://localhost:3000",    # 프론트엔드 개발 서버
        "http://127.0.0.1:8501",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
