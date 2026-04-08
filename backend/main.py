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
  3. FDS ML 모델 로드 (파일 존재 시)
═══════════════════════════════════════════════════════════════
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.models.database import init_db, seed_dummy_data
from app.services.model_service import fds_service
from app.routers import fds, accounts

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

    시작 시:
      1. DB 초기화 (테이블 자동 생성)
      2. 더미 데이터 삽입
      3. ML 모델 로드

    ※ FastAPI의 lifespan 패턴을 사용하여
      startup/shutdown 이벤트를 관리합니다.
    """
    # ── Startup ──
    logger.info("=" * 60)
    logger.info("  Fintech FDS Agent Server Starting...")
    logger.info("=" * 60)

    # 1단계: DB 초기화
    logger.info("[INIT] 1/3 - 데이터베이스 초기화 중...")
    init_db()

    # 2단계: 더미 데이터
    logger.info("[INIT] 2/3 - 더미 데이터 확인 중...")
    seed_dummy_data()

    # 3단계: ML 모델 로드
    logger.info("[INIT] 3/3 - FDS 모델 로드 중...")
    fds_service.load_models(settings.MODEL_DIR)

    mode = "ML Stacking Ensemble" if fds_service.is_ml_mode else "Rule-Based Engine"
    logger.info(f"[INIT] 추론 엔진: {mode}")
    logger.info("=" * 60)
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
