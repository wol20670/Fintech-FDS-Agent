# 🛡️ Fintech FDS Agent
### 실시간 지능형 사기 탐지 및 자율 대응 에이전트

> 캡스톤 디자인 프로젝트 | 2023162504 원병찬 / 2023162503 양승빈

---

## 📌 프로젝트 개요

비대면 금융 거래의 급증과 함께 사기 수법도 빠르게 지능화되고 있습니다.
기존 **규칙 기반(Rule-Based) FDS**는 사기꾼이 규칙을 학습해 우회하면 즉시 무력화되는 한계가 있었습니다.

이 프로젝트는 **ML 모델 기반의 자율 판단 시스템**으로,

- 실시간 거래를 **100ms 이내**에 심사하고
- 위험 점수에 따라 **자동 승인 → 추가인증 → 차단 → 계좌 동결**을 자율 수행하며
- 모델이 왜 그 판단을 내렸는지 **설명 가능한 AI(XAI)** 로 근거를 함께 제공합니다

---

## 🗂️ 데이터셋

### PaySim (Kaggle)

실제 금융 데이터는 개인정보 보호로 접근이 불가하여,
실제 모바일 금융 서비스의 거래 패턴을 통계적으로 모방한 합성 데이터셋을 활용했습니다.

| 항목 | 내용 |
|------|------|
| 총 거래 건수 | **6,362,620건** |
| 사기 거래 비율 | 약 **0.13%** (극심한 불균형) |
| 주요 컬럼 | `step`, `type`, `amount`, `nameOrig`, `oldbalanceOrg`, `newbalanceOrig`, `nameDest`, `oldbalanceDest`, `newbalanceDest`, `isFraud` |

> ⚠️ `Fraud.csv` 파일은 용량 문제로 저장소에 포함되지 않습니다.
> Kaggle의 [PaySim Financial Fraud Detection Dataset](https://www.kaggle.com/datasets/ealaxi/paysim1)에서 직접 다운로드 후 Colab에 업로드하세요.

### 데이터 불균형 해결 — 하이브리드 샘플링

전체 데이터의 0.13%만이 사기인 극심한 불균형 문제를 해결하기 위해,
단순 SMOTE 대신 **2단계 하이브리드 샘플링** 전략을 적용했습니다.

```
Step 1. RandomUnderSampler  →  정상:사기 = 10:1 로 정상 데이터 축소
Step 2. SMOTE               →  사기 데이터를 정상 데이터의 50% 수준까지 증식
```

### 피처 엔지니어링

원본 컬럼 외에 도메인 지식 기반의 파생 피처를 직접 생성했습니다.

| 피처 | 설명 |
|------|------|
| `balance_diff_orig` | `거래 전 잔액 - 거래 후 잔액 - 거래 금액` → 0이면 정상, 클수록 의심 |
| `balance_diff_dest` | 수취인 측 잔액 불일치 탐지 |
| `orig_is_customer` | 송금인이 개인 계좌(C)인지 가맹점(M)인지 구분 |
| `dest_is_merchant` | 수취인이 가맹점이면 사기 확률 낮음 |

---

## 🧠 모델 구조 — Stacking Ensemble

```
[입력 데이터]
     │
     ├─── XGBoost  ───→  사기 확률 P1
     │
     └─── LightGBM ───→  사기 확률 P2
                               │
                      [P1, P2] 결합
                               │
               Logistic Regression (메타 모델)
                               │
                     최종 사기 확률 (0.0 ~ 1.0)
```

XGBoost와 LightGBM이 각각 독립적으로 사기 확률을 예측하고,
Logistic Regression 메타 모델이 두 예측을 종합하여 최종 확률을 산출합니다.

### 최종 모델 성능

| 지표 | 결과 | 의미 |
|------|------|------|
| **ROC-AUC** | **0.9997** | 정상/사기 구분 능력 거의 완벽 |
| **Recall** | **99.70%** | 실제 사기 1,000건 중 997건 탐지 |
| **Precision** | **96.30%** | 사기 판정 중 실제 사기 비율 |
| **F1-Score** | **0.9797** | Precision과 Recall의 조화 평균 |

> 금융 보안에서는 사기를 놓치는 것(미탐)이 정상을 차단하는 것(오탐)보다 훨씬 큰 피해를 야기합니다.
> 따라서 **Recall을 핵심 지표**로 설정했습니다.

---

## 🏗️ 시스템 아키텍처

```
Fintech_FDS_Agent_v1/
│
├── better_agent_v1.ipynb      ← 모델 학습 (Google Colab)
│
├── backend/                   ← FastAPI 서버
│   ├── main.py                ← 서버 진입점 (MLOps 파이프라인 포함)
│   ├── model_loader.py        ← 동적 모델 로더 (Google Drive → 로컬 캐싱)
│   ├── requirements.txt
│   ├── models/                ← 서버 기동 시 자동 생성 및 다운로드
│   ├── data/                  ← SQLite DB 자동 생성
│   └── app/
│       ├── config.py          ← 임계값 등 설정
│       ├── models/database.py ← DB 스키마 및 더미 데이터
│       ├── schemas/telegram.py← 거래 전문 스키마 (Request/Response)
│       ├── services/model_service.py ← ML 추론 엔진
│       └── routers/
│           ├── fds.py         ← /api/v1/fds/* 엔드포인트
│           └── accounts.py    ← /api/v1/accounts/* 엔드포인트
│
├── dashboard.py               ← Streamlit 대시보드 진입점
└── dashboard/                 ← 대시보드 모듈
    ├── utils/
    │   ├── constants.py       ← 더미 계좌, 시나리오, 색상 매핑
    │   ├── api_client.py      ← 백엔드 HTTP 통신 전담
    │   └── session.py         ← 세션 상태 관리
    ├── components/
    │   ├── sidebar.py         ← 사이드바 (시나리오 버튼, 통계)
    │   └── result_card.py     ← 심사 결과 카드 + 게이지
    └── pages/
        ├── tab_evaluate.py    ← 거래 심사 탭
        ├── tab_logs.py        ← 심사 이력 탭
        └── tab_stats.py       ← 통계 분석 탭
```

### FDS 자율 대응 흐름

| 위험 등급 | 점수 범위 | 자율 대응 |
|-----------|-----------|-----------|
| 🟢 SAFE | 0.00 ~ 0.10 | 자동 승인 |
| 🟡 LOW | 0.10 ~ 0.30 | 승인 + 로그 강화 |
| 🟠 MEDIUM | 0.30 ~ 0.60 | SMS/ARS 추가 인증 요청 |
| 🔴 HIGH | 0.60 ~ 0.85 | 즉시 거래 차단 |
| 🚨 CRITICAL | 0.85 ~ 1.00 | 계좌 동결 |

---

## ☁️ MLOps 아키텍처 — 동적 모델 로딩

### 설계 원칙

모델 바이너리(`.pkl`)는 소스코드와 완전히 분리하여 관리합니다.

```
Git 저장소 (코드)          정적 스토리지 (모델)
──────────────            ──────────────────────
main.py                   Google Drive
model_loader.py    ←───   base_models.pkl
requirements.txt          meta_model.pkl
...
```

### 서버 기동 시 자동 파이프라인

```
서버 시작 (uvicorn)
      │
      ▼
backend/models/ 에 .pkl 존재 여부 확인
      │
  ┌───┴────────────────────┐
  │ 없음                   │ 있음 (캐시 히트)
  ▼                        ▼
Google Drive에서         즉시 joblib.load()
gdown으로 자동 Pull
      │
      ▼
  joblib.load()
      │
      ▼
fds_service (글로벌 객체) 바인딩
      │
      ▼
  ML 모드 활성화
  (실패 시 → Rule-Based 폴백)
```

### 현업 인프라와의 논리적 동일성

> **한 줄 요약:** 정적 스토리지(Google Drive / S3)에서 모델 아티팩트를 서버 기동 시점에 On-demand Pull하여 로컬에 캐싱한 뒤 글로벌 인퍼런스 객체에 바인딩하는 구조는, AWS SageMaker·GCP Vertex AI가 S3/GCS에서 모델을 컨테이너 내 `/tmp/` 로 Pull하여 서빙하는 메커니즘과 완전히 동일한 패턴입니다.

| 항목 | 본 프로젝트 | 현업 (AWS) |
|------|-------------|------------|
| 모델 저장소 | Google Drive | S3 Model Registry |
| Pull 방식 | gdown | boto3.download_file() |
| 로컬 캐싱 경로 | backend/models/ | /tmp/model/ (컨테이너) |
| 서빙 진입점 | FastAPI lifespan | SageMaker Endpoint |
| 폴백 전략 | Rule-Based 엔진 | 이전 버전 모델 |
| 멱등성 보장 | 파일 존재 체크 | ETag / 버전 해시 비교 |

> **전환 방법:** `model_loader.py` 의 `STORAGE_URLS` 딕셔너리 값만
> S3 presigned URL 로 교체하면 됩니다. 나머지 코드는 변경 불필요.

---

## 🚀 실행 방법

### 사전 준비

- Python 3.9 이상

### Step 1 — 백엔드 서버 실행

```bash
cd backend

# 가상환경 생성 및 활성화 (처음 한 번만)
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Mac / Linux

# 패키지 설치 (처음 한 번만)
pip install -r requirements.txt
pip install streamlit plotly  # 대시보드용

# 서버 실행
uvicorn main:app --reload --port 8000
```

> 📥 서버 최초 기동 시 `backend/models/` 폴더에 모델 파일이 없으면
> **자동으로 Google Drive에서 다운로드**합니다. (약 30초 소요)
> 이후 재실행부터는 캐시된 파일을 즉시 로드합니다.

서버가 뜨면 아래 주소에서 API 문서를 확인할 수 있습니다.
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

### Step 2 — Streamlit 대시보드 실행

```bash
# 프로젝트 루트에서 실행 (backend 폴더 아님)
streamlit run dashboard.py
```

브라우저에서 http://localhost:8501 로 접속하면 시뮬레이션 대시보드가 열립니다.

---

## 🖥️ 시뮬레이션 대시보드

FastAPI 백엔드와 연동되는 실거래 시뮬레이션 UI입니다.

### 주요 기능

| 탭 | 기능 |
|----|------|
| 🔍 거래 심사 | 더미 계좌 선택 → 파라미터 설정 → FDS 심사 실행 → 리스크 게이지 확인 |
| 📋 심사 이력 | 세션 로그 + 서버 DB 로그 동시 조회, 등급/조치별 필터 |
| 📊 통계 분석 | 위험 등급 파이차트, 시간대별 바차트, 세션 스캐터 플롯 |

### 사이드바 빠른 시나리오

| 시나리오 | 예상 결과 |
|----------|-----------|
| 🟢 정상 소액 이체 | SAFE → 자동 승인 |
| 🟡 잔액 대비 고액 이체 | LOW ~ MEDIUM |
| 🟠 신규기기 + 신규수취인 고액 | HIGH → 거래 차단 |
| 🔴 고위험 계좌 대량 이체 | CRITICAL → 계좌 동결 |
| 🚨 잔액 초과 거래 | CRITICAL → 즉시 차단 |

---

## 🔌 API 엔드포인트

| Method | 경로 | 설명 |
|--------|------|------|
| `POST` | `/api/v1/fds/evaluate` | 단건 거래 FDS 심사 |
| `POST` | `/api/v1/fds/batch` | 배치(다건) 거래 분석 |
| `GET` | `/api/v1/fds/health` | 서비스 상태 확인 |
| `GET` | `/api/v1/fds/logs` | 심사 이력 조회 |
| `GET` | `/api/v1/fds/stats` | 통계 데이터 (대시보드용) |
| `GET` | `/api/v1/accounts/` | 전체 계좌 목록 조회 |

---

## 🛠️ 기술 스택

| 구분 | 기술 |
|------|------|
| ML 모델 | XGBoost, LightGBM, Scikit-learn (Stacking Ensemble) |
| 불균형 처리 | Imbalanced-learn (SMOTE + RandomUnderSampler) |
| 백엔드 | FastAPI, Pydantic, SQLite |
| 프론트엔드 | Streamlit, Plotly |
| MLOps | gdown, Google Drive (정적 모델 스토리지) |
| 학습 환경 | Google Colab |
| 모델 직렬화 | Joblib |

---

## 📈 현재 진행 상황

- [x] 데이터 전처리 및 피처 엔지니어링
- [x] XGBoost + LightGBM Stacking Ensemble 학습 (ROC-AUC 0.9997)
- [x] FastAPI 백엔드 구축 (거래 심사 / 배치 분석 / 심사 이력 / 통계)
- [x] SQLite 기반 거래 원장 및 FDS 감사 로그 DB
- [x] Rule-Based 폴백 엔진 (모델 파일 없이도 동작)
- [x] Streamlit 실거래 시뮬레이션 대시보드 (모듈화 완료)
- [x] MLOps 동적 모델 로딩 (Google Drive → Startup 자동 Pull → 로컬 캐싱)
- [ ] SHAP 기반 XAI 고도화
- [ ] Docker 컨테이너화 및 클라우드 배포
- [ ] LSTM / GNN 기반 시계열·네트워크 분석 도입

---

## 📁 .gitignore 주요 제외 항목

```
backend/.venv/          # 가상환경
backend/data/*.db       # SQLite DB (서버 실행 시 자동 생성)
backend/models/*.pkl    # 학습된 모델 파일 (서버 기동 시 자동 다운로드)
```

모델 파일(`.pkl`)은 용량 문제로 저장소에 포함되지 않습니다.
서버 최초 기동 시 `model_loader.py` 가 Google Drive에서 자동으로 다운로드합니다.

---

## 📝 향후 계획

본 프로젝트는 추후 논문으로 정리하여 학술지 또는 학술대회에 게재할 예정입니다.