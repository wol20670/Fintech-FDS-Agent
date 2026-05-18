"""
═══════════════════════════════════════════════════════════════
Fintech FDS Agent - FastAPI 메인 서버
═══════════════════════════════════════════════════════════════
지능형 사기 탐지 및 자율 대응 에이전트의 백엔드 서버.

실행 방법:
  $ cd backend
  $ uvicorn main:app --reload --port 8000

API 문서 확인:
  - Swagger UI : http://localhost:8000/docs
  - ReDoc      : http://localhost:8000/redoc

서버 시작 시 자동 수행:
  1. SQLite DB 테이블 생성 (IF NOT EXISTS)
  2. 더미 데이터 삽입 (최초 1회)
  3. backend/models/ 에 .pkl 파일 존재 확인
     → 없으면 Google Drive(정적 스토리지)에서 자동 다운로드
     → 있으면 캐시 히트 → 즉시 로드 (멱등성 보장)
  4. FDS ML 모델 글로벌 객체 바인딩

[MLOps 아키텍처 메모]
  Git 저장소  → 코드만 관리 (.pkl 은 .gitignore)
  정적 스토리지(Google Drive / 현업: S3, GCS) → 모델 바이너리 관리
  서버 Startup → 스토리지에서 Pull → 로컬 캐싱 → 서빙
  이 패턴이 SageMaker / Vertex AI 모델 서빙의 핵심 메커니즘과 동일함.
═══════════════════════════════════════════════════════════════
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models.database import init_db, seed_dummy_data
from app.services.model_service_v2 import fds_service
from app.routers import fds, accounts

# ── model_loader: 동적 모델 다운로드 + 로드 파이프라인 ──
# 이 모듈만 교체하면 Google Drive → S3/GCS 전환 가능
from model_loader import initialize_model_pipeline

# ── 로깅 설정 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


# ════════════════════════════════════════════
# 서버 Lifespan (시작/종료 이벤트)
# ════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    서버 시작/종료 시 실행되는 로직.

    [Startup 시퀀스]
      1. DB 초기화 (테이블 자동 생성, IF NOT EXISTS → 멱등성)
      2. 더미 데이터 삽입 (최초 1회)
      3. 모델 파이프라인 초기화
         a. backend/models/ 에 .pkl 파일 있는지 체크
         b. 없으면 Google Drive에서 gdown으로 자동 Pull
         c. joblib.load() → fds_service 글로벌 객체에 바인딩
         d. 실패 시 Rule-Based 폴백 (Graceful Degradation)
    """
    logger.info("=" * 60)
    logger.info("  Fintech FDS Agent Server Starting...")
    logger.info("=" * 60)

    # ── Step 1: DB 초기화 ──
    logger.info("[INIT] 1/3 - 데이터베이스 초기화 중...")
    init_db()

    # ── Step 2: 더미 데이터 ──
    logger.info("[INIT] 2/3 - 더미 데이터 확인 중...")
    seed_dummy_data()

    # ── Step 3: 모델 파이프라인 (핵심 변경 부분) ──
    logger.info("[INIT] 3/3 - FDS 모델 파이프라인 초기화 중...")
    logger.info("       (모델 파일 없으면 정적 스토리지에서 자동 다운로드)")

    # initialize_model_pipeline:
    #   ① 파일 체크 → ② 없으면 Google Drive Pull → ③ joblib.load()
    #   현업 전환 시 이 함수 내부의 URL만 S3 presigned URL로 교체하면 됨
    mode = await initialize_model_pipeline(fds_service)

    logger.info("=" * 60)
    logger.info(f"  추론 엔진: {mode}")
    logger.info("  Server Ready! → http://localhost:8000/docs")
    logger.info("=" * 60)

    yield  # 서버 실행 중...

    # ── Shutdown ──
    logger.info("[SHUTDOWN] FDS Agent Server 종료")


# ════════════════════════════════════════════
# FastAPI 앱 생성
# ════════════════════════════════════════════

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="""
## 지능형 사기 탐지 및 자율 대응 에이전트 (FDS Agent) API

### 개요
실시간 금융 거래 데이터를 분석하여 사기 여부를 판단하고,
위험 점수에 따라 **자율 대응**(승인/추가인증/차단/동결)하는 AI 에이전트입니다.

### MLOps 아키텍처
- 모델 바이너리(.pkl)는 Git 저장소에서 분리하여 정적 스토리지(Google Drive)에서 관리
- 서버 기동 시 자동 다운로드 → 로컬 캐싱 → ML 모드 활성화
- 다운로드 실패 시 Rule-Based 폴백으로 서비스 무중단 보장

### 주요 기능
- **실시간 단건 심사**: 거래 전문(Telegram)을 받아 즉시 사기 판단
- **배치 분석**: 대량 거래 데이터 일괄 분석
- **XAI**: 모델의 판단 근거를 자연어로 설명
- **감사 추적**: 모든 심사 결과를 DB에 기록

### 기술 스택
- **ML Model**: XGBoost + LightGBM Stacking Ensemble
- **데이터**: PaySim 합성 금융 거래 데이터 (630만건)
- **성능**: Recall 99.76% | ROC-AUC 0.9996
    """,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)


# ── CORS 미들웨어 (Streamlit 연동용) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 라우터 등록 ──
app.include_router(fds.router)
app.include_router(accounts.router)


# ── 루트 엔드포인트 ──
@app.get("/", tags=["서버 정보"])
async def root():
    """서버 기본 정보 반환."""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "model_mode": "ML" if fds_service.is_ml_mode else "Rule-Based",
        "docs": "/docs",
        "redoc": "/redoc",
    }