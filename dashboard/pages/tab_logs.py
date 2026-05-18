"""
심사 이력 탭
- 세션 내 로그 테이블 (위험등급별 색상)
- 서버 DB 로그 조회
- 등급 / 조치 필터
"""

import pandas as pd
import streamlit as st
from utils import fetch_fds_logs


def render():
    st.markdown("#### 📋 시뮬레이션 심사 이력")

    # ── 필터 ──
    c1, c2 = st.columns(2)
    filter_level  = c1.multiselect("위험 등급", ["SAFE","LOW","MEDIUM","HIGH","CRITICAL"])
    filter_action = c2.multiselect("조치",       ["APPROVE","ADDITIONAL_AUTH","BLOCK","FREEZE"])

    # ── 세션 로그 ──
    if st.session_state.sim_logs:
        df = pd.DataFrame(st.session_state.sim_logs)
        if filter_level:
            df = df[df["위험등급"].isin(filter_level)]
        if filter_action:
            df = df[df["조치"].isin(filter_action)]

        st.dataframe(
            df.style.map(_color_risk, subset=["위험등급"]),
            use_container_width=True,
            height=400,
        )
        st.caption(f"총 {len(df)}건 표시 (최근 50건 보관)")
    else:
        st.info("아직 심사 이력이 없습니다. '거래 심사' 탭에서 FDS 심사를 실행해 보세요.")

    # ── 서버 DB 로그 ──
    server_logs = fetch_fds_logs(
        risk_level=filter_level[0] if len(filter_level) == 1 else None,
        limit=100,
    )
    if server_logs:
        st.markdown("---")
        st.markdown("#### 🗄️ 서버 DB 심사 로그")
        df_s = pd.DataFrame(server_logs)
        cols = [c for c in ["created_at","telegram_no","risk_level",
                             "risk_score","action_taken","processing_ms","reason"]
                if c in df_s.columns]
        st.dataframe(df_s[cols], use_container_width=True, height=300)


def _color_risk(val: str) -> str:
    colors = {
        "SAFE":     "background-color:#f0fdf4",
        "LOW":      "background-color:#f7fee7",
        "MEDIUM":   "background-color:#fffbeb",
        "HIGH":     "background-color:#fff7ed",
        "CRITICAL": "background-color:#fef2f2",
        "ERROR":    "background-color:#f5f5f5",
    }
    return colors.get(val, "")