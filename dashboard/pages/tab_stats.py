"""
통계 분석 탭
- 서버 API 기반 통계 (총 심사, 평균 응답, 위험 분포, 시간대 추이)
- 세션 내 시뮬레이션 통계 (등급 분포 바, 리스크 점수 스캐터)
"""

import pandas as pd
import streamlit as st
import plotly.express as px
from utils import fetch_fds_stats, RISK_COLOR


def render():
    st.markdown("#### 📊 FDS 심사 통계")

    server_stats = fetch_fds_stats()

    # ── 서버 통계 ──
    if server_stats:
        _render_server_stats(server_stats)
    
    # ── 세션 통계 ──
    if st.session_state.sim_logs:
        st.markdown("---")
        _render_session_stats()

    if not server_stats and not st.session_state.sim_logs:
        st.info("서버에 연결하고 심사를 실행하면 통계가 표시됩니다.")


def _render_server_stats(stats: dict):
    total     = stats.get("total_evaluations", 0)
    avg_ms    = stats.get("avg_processing_ms", 0)
    risk_dist = stats.get("risk_distribution", {})
    blocked   = risk_dist.get("HIGH", 0) + risk_dist.get("CRITICAL", 0)
    safe      = risk_dist.get("SAFE", 0) + risk_dist.get("LOW", 0)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총 심사 건수",  f"{total:,}")
    c2.metric("평균 응답시간", f"{avg_ms:.1f}ms")
    c3.metric("고위험 탐지",   f"{blocked:,}")
    c4.metric("정상 처리",     f"{safe:,}")

    st.markdown("---")
    c_pie, c_bar = st.columns(2)

    with c_pie:
        if risk_dist:
            fig = px.pie(
                names=list(risk_dist.keys()),
                values=list(risk_dist.values()),
                title="위험 등급별 분포",
                color=list(risk_dist.keys()),
                color_discrete_map=RISK_COLOR,
                hole=0.4,
            )
            fig.update_layout(height=320, margin=dict(t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)

    with c_bar:
        hourly = stats.get("hourly_trend", [])
        if hourly:
            df_h = pd.DataFrame(hourly)
            fig = px.bar(df_h, x="hour", y="count",
                         title="최근 24시간 심사 건수",
                         labels={"hour": "시간(시)", "count": "건수"},
                         color_discrete_sequence=["#3b82f6"])
            fig.update_layout(height=320, margin=dict(t=40, b=10))
            st.plotly_chart(fig, use_container_width=True)


def _render_session_stats():
    st.markdown("#### 🧪 현재 세션 통계")
    df = pd.DataFrame(st.session_state.sim_logs)

    c1, c2 = st.columns(2)
    with c1:
        cnt = df["위험등급"].value_counts().reset_index()
        cnt.columns = ["위험등급", "건수"]
        fig = px.bar(cnt, x="위험등급", y="건수",
                     title="세션 위험 등급 분포",
                     color="위험등급", color_discrete_map=RISK_COLOR)
        fig.update_layout(height=300, margin=dict(t=40, b=10), showlegend=False)
        st.plotly_chart(fig, use_container_width=True)

    with c2:
        fig = px.scatter(
            df, x=df.index, y="점수",
            color="위험등급", color_discrete_map=RISK_COLOR,
            title="심사 순서별 리스크 점수",
            labels={"x": "순서", "점수": "리스크 점수(%)"},
        )
        fig.update_layout(height=300, margin=dict(t=40, b=10))
        st.plotly_chart(fig, use_container_width=True)

    avg_resp = df["응답(ms)"].mean()
    st.caption(f"세션 평균 응답시간: **{avg_resp:.1f}ms** | 총 {len(df)}건")