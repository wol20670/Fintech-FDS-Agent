"""
FDS Agent 시뮬레이션 대시보드 - 메인 진입점

실행:
  streamlit run dashboard.py

폴더 구조:
  dashboard.py          <- 여기 (진입점)
  dashboard/
    utils/
      constants.py      <- 상수, 더미 데이터, 색상 매핑
      api_client.py     <- FastAPI 백엔드 HTTP 통신 전담
      session.py        <- 세션 상태 관리, payload 빌더
    components/
      sidebar.py        <- 사이드바 (서버 상태, 시나리오 버튼, 통계)
      result_card.py    <- 심사 결과 카드 + 게이지 + 상세 정보
    pages/
      tab_evaluate.py   <- 거래 심사 탭
      tab_logs.py       <- 심사 이력 탭
      tab_stats.py      <- 통계 분석 탭
"""

import sys
from pathlib import Path

# dashboard/ 패키지를 임포트 경로에 추가
sys.path.insert(0, str(Path(__file__).parent / "dashboard"))

import streamlit as st
from utils.session import init_session
from components.sidebar import render_sidebar
from pages import tab_evaluate, tab_logs, tab_stats

# -- 페이지 설정 --
st.set_page_config(
    page_title="FDS Agent 시뮬레이션 대시보드",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -- 공통 CSS --
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
        padding: 1.5rem 2rem; border-radius: 12px;
        margin-bottom: 1.5rem; color: white;
    }
    .main-header h1 { margin: 0; font-size: 1.8rem; font-weight: 700; }
    .main-header p  { margin: 0.3rem 0 0; opacity: 0.75; font-size: 0.9rem; }

    .result-safe     { background:#f0fdf4; border-left:5px solid #22c55e; border-radius:8px; padding:1rem 1.2rem; }
    .result-low      { background:#f7fee7; border-left:5px solid #84cc16; border-radius:8px; padding:1rem 1.2rem; }
    .result-medium   { background:#fffbeb; border-left:5px solid #f59e0b; border-radius:8px; padding:1rem 1.2rem; }
    .result-high     { background:#fff7ed; border-left:5px solid #f97316; border-radius:8px; padding:1rem 1.2rem; }
    .result-critical { background:#fef2f2; border-left:5px solid #ef4444; border-radius:8px; padding:1rem 1.2rem; }
</style>
""", unsafe_allow_html=True)

# -- 초기화 --
init_session()

# -- 헤더 --
st.markdown("""
<div class="main-header">
  <h1>🛡️ FDS Agent 실거래 시뮬레이션</h1>
  <p>더미 계좌를 이용한 이상 거래 탐지 시스템 · XGBoost + LightGBM Stacking Ensemble</p>
</div>
""", unsafe_allow_html=True)

# -- 사이드바 (서버 상태 반환) --
server_ok = render_sidebar()

# -- 탭 --
tab1, tab2, tab3 = st.tabs(["🔍 거래 심사", "📋 심사 이력", "📊 통계 분석"])

with tab1:
    tab_evaluate.render(server_ok)

with tab2:
    tab_logs.render()

with tab3:
    tab_stats.render()