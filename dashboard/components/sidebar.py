"""
사이드바 컴포넌트
- 서버 상태 표시
- 빠른 시나리오 버튼
- 세션 통계 요약
"""

import pandas as pd
import streamlit as st
from utils import check_server, apply_scenario, SCENARIOS


def render_sidebar() -> bool:
    """
    사이드바 전체 렌더링.
    Returns: server_ok (bool)
    """
    with st.sidebar:
        st.markdown("## 🛡️ FDS Agent")
        st.markdown("---")

        # ── 서버 상태 ──
        server_ok, health = check_server()
        if server_ok:
            st.markdown("🟢 **서버 연결됨** (localhost:8000)")
            mode = health.get("model_mode", "Unknown")
            st.caption(f"추론 엔진: **{mode}**")
        else:
            st.markdown("🔴 **서버 연결 실패**")
            st.caption("`uvicorn main:app --reload --port 8000`")

        st.markdown("---")

        # ── 빠른 시나리오 ──
        st.markdown("### ⚡ 빠른 시나리오")
        for sc in SCENARIOS:
            if st.button(sc["label"], key=f"sc_{sc['label']}", use_container_width=True):
                apply_scenario(sc["params"])
                st.rerun()
            st.caption(sc["desc"])
            st.markdown("")

        st.markdown("---")

        # ── 세션 통계 요약 ──
        if st.session_state.sim_logs:
            st.markdown("### 📊 세션 통계")
            df      = pd.DataFrame(st.session_state.sim_logs)
            total   = len(df)
            blocked = df["조치"].isin(["BLOCK", "FREEZE"]).sum()
            st.metric("총 심사", total)
            c1, c2 = st.columns(2)
            c1.metric("승인", total - blocked)
            c2.metric("차단", int(blocked))

            if st.button("🗑️ 기록 초기화", use_container_width=True):
                st.session_state.sim_logs    = []
                st.session_state.last_result = None
                st.rerun()

    return server_ok