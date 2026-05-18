"""
═══════════════════════════════════════════════════════════════
model_loader.py  —  FDS 동적 모델 로더 (Dynamic Model Loader)
═══════════════════════════════════════════════════════════════

[MLOps 아키텍처 설계 메모]
──────────────────────────────────────────────────────────────
현업 인프라(AWS S3 + SageMaker / GCS + Vertex AI)와의 논리적
동일성:

  현업 패턴:
    S3://model-registry/{model_name}/{version}/artifacts/*.pkl
      → SageMaker Endpoint 기동 시 S3에서 /tmp/model/ 로 Pull
      → joblib.load() → 글로벌 인퍼런스 객체 바인딩 → 서빙

  본 프로젝트 패턴:
    Google Drive (정적 스토리지)
      → FastAPI Startup 시 backend/models/ 로 Pull (gdown)
      → joblib.load() → 글로벌 FDSModelService 바인딩 → 서빙

  핵심 메커니즘이 동일한 이유:
    ① 모델 바이너리를 소스코드(.git)와 완전 분리 (Model Registry 원칙)
    ② 서버 기동 시점에 On-demand Pull → 로컬 캐싱 (불변 아티팩트)
    ③ 파일 존재 여부 체크로 멱등성(Idempotency) 보장
       → 이미 다운된 경우 재다운로드 없이 바로 로드 (비용·시간 절감)
    ④ 로드 실패 시 Rule-Based 폴백 → 서비스 무중단 보장 (Graceful Degradation)

  실제 운영으로 확장 시 교체 지점:
    - STORAGE_URLS 딕셔너리의 값만 S3 presigned URL / GCS signed URL 로 교체
    - gdown → boto3.download_file() / google.cloud.storage 로 교체
    - 이 파일(model_loader.py) 외 나머지 코드는 변경 불필요
──────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ════════════════════════════════════════════
# 스토리지 설정 (여기만 바꾸면 S3/GCS로 전환됨)
# ════════════════════════════════════════════

# Google Drive File ID → gdown이 인식하는 직접 다운로드 URL로 변환
# 현업 전환 시: S3 presigned URL 또는 GCS signed URL 로 교체
STORAGE_URLS: dict[str, str] = {
    "base_models.pkl": "https://drive.google.com/uc?id=1lQkr-2GExdDIX319IPgjHfF8jZPJOTQU",
    "meta_model.pkl":  "https://drive.google.com/uc?id=1erxqfnpUqHxXNBjFKWPJ8d9Pq1KngAWf",
}

# 모델 저장 경로 (backend/models/)
MODEL_DIR = Path(__file__).resolve().parent / "models"


# ════════════════════════════════════════════
# 다운로드 헬퍼
# ════════════════════════════════════════════

def _ensure_gdown() -> bool:
    """
    gdown 라이브러리 설치 여부 확인.
    없으면 pip install 시도 후 재확인.

    gdown: Google Drive 파일 다운로드 전용 라이브러리.
    현업에서 S3를 쓸 경우 boto3.download_file()로 교체.
    """
    try:
        import gdown  # noqa: F401
        return True
    except ImportError:
        logger.warning("[MODEL_LOADER] gdown 미설치 → 자동 설치 시도...")
        import subprocess, sys
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "gdown", "-q"],
            capture_output=True,
        )
        if result.returncode == 0:
            logger.info("[MODEL_LOADER] gdown 설치 완료")
            return True
        logger.error(f"[MODEL_LOADER] gdown 설치 실패: {result.stderr.decode()}")
        return False


def _download_file(url: str, dest: Path) -> bool:
    """
    단일 파일 다운로드.

    gdown 사용 이유:
      - Google Drive의 바이러스 스캔 경고(confirm 토큰) 자동 처리
      - 현업에서 S3라면 boto3.download_file() 또는 requests.get()으로 대체

    Args:
        url:  다운로드 URL (Google Drive uc?id=... 형식)
        dest: 저장할 로컬 경로

    Returns:
        True if success, False if failed
    """
    import gdown

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"[MODEL_LOADER] 다운로드 시작: {dest.name}")

    try:
        # gdown.download: URL은 uc?id=... 형식으로 직접 전달 (fuzzy 옵션 미사용)
        output = gdown.download(url, str(dest), quiet=False)
        if output and dest.exists() and dest.stat().st_size > 0:
            size_kb = dest.stat().st_size / 1024
            logger.info(f"[MODEL_LOADER] ✅ 다운로드 완료: {dest.name} ({size_kb:.1f} KB)")
            return True
        else:
            logger.error(f"[MODEL_LOADER] ❌ 다운로드 실패 (파일 없음 또는 크기 0): {dest.name}")
            return False

    except Exception as e:
        logger.error(f"[MODEL_LOADER] ❌ 다운로드 예외: {dest.name} → {e}")
        # 실패한 빈 파일 정리
        if dest.exists() and dest.stat().st_size == 0:
            dest.unlink(missing_ok=True)
        return False


# ════════════════════════════════════════════
# 메인 퍼블릭 함수: 파일 체크 → 다운로드 → 로드
# ════════════════════════════════════════════

def ensure_models_available() -> bool:
    """
    모델 파일 존재 확인 → 없으면 다운로드.

    멱등성(Idempotency) 보장:
      이미 파일이 존재하면 다운로드 없이 즉시 True 반환.
      → Kubernetes Pod 재시작, EC2 재부팅 등 상황에서
        불필요한 재다운로드를 방지 (현업 원칙과 동일).

    Returns:
        True  → 모든 모델 파일 준비 완료
        False → 하나 이상 다운로드 실패
    """
    all_ok = True

    for filename, url in STORAGE_URLS.items():
        dest = MODEL_DIR / filename

        # ── 이미 존재하면 스킵 (멱등성) ──
        if dest.exists() and dest.stat().st_size > 0:
            size_kb = dest.stat().st_size / 1024
            logger.info(
                f"[MODEL_LOADER] ✅ 캐시 히트: {filename} ({size_kb:.1f} KB) → 다운로드 스킵"
            )
            continue

        # ── gdown 의존성 확인 ──
        if not _ensure_gdown():
            logger.error("[MODEL_LOADER] gdown 사용 불가 → 해당 파일 다운로드 스킵")
            all_ok = False
            continue

        # ── 다운로드 실행 ──
        success = _download_file(url, dest)
        if not success:
            all_ok = False

    return all_ok


def load_models_to_service(model_service) -> bool:
    """
    다운로드된 .pkl 파일을 FDSModelService에 로드.

    이 함수는 app/services/model_service.py 의
    FDSModelService.load_models() 를 호출하여
    글로벌 인퍼런스 객체(fds_service)에 모델을 바인딩합니다.

    Args:
        model_service: FDSModelService 싱글톤 인스턴스

    Returns:
        True  → ML 모드 로드 성공
        False → 로드 실패 (Rule-Based 폴백으로 이어짐)
    """
    try:
        model_service.load_models(str(MODEL_DIR))
        if model_service.is_ml_mode:
            logger.info("[MODEL_LOADER] 🚀 ML Stacking Ensemble 모드 활성화 완료")
            return True
        else:
            logger.warning("[MODEL_LOADER] ⚠️ 모델 로드 실패 → Rule-Based 폴백 모드")
            return False
    except Exception as e:
        logger.error(f"[MODEL_LOADER] 모델 서비스 로드 예외: {e}")
        return False


async def initialize_model_pipeline(model_service) -> str:
    """
    서버 Startup에서 호출할 전체 파이프라인.

    흐름:
      1. backend/models/ 에 .pkl 파일 존재 확인
      2. 없으면 Google Drive(정적 스토리지)에서 Pull
      3. joblib.load() → fds_service 글로벌 객체에 바인딩

    Returns:
        "ML"         → ML 모델 로드 성공
        "Rule-Based" → 다운로드/로드 실패, 폴백 동작
    """
    logger.info("[MODEL_LOADER] ════ 모델 파이프라인 초기화 시작 ════")

    # Step 1: 파일 존재 확인 및 다운로드
    download_ok = ensure_models_available()

    if not download_ok:
        logger.warning(
            "[MODEL_LOADER] 일부 모델 파일 다운로드 실패 → Rule-Based 폴백으로 계속 진행"
        )
        # Graceful Degradation: 서비스 중단 없이 Rule-Based로 서빙
        return "Rule-Based"

    # Step 2: 모델 로드 → 글로벌 서비스 객체에 바인딩
    load_ok = load_models_to_service(model_service)

    mode = "ML" if load_ok else "Rule-Based"
    logger.info(f"[MODEL_LOADER] ════ 파이프라인 완료 → 추론 모드: {mode} ════")
    return mode