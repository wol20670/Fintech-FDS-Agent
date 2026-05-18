"""
심사 결과 렌더링 컴포넌트
- 위험 등급 카드
- 리스크 게이지 차트
- 전문 상세 정보 expander
"""

import streamlit as st
import plotly.graph_objects as go
from utils.constants import ACCOUNTS, RISK_COLOR, RISK_EMOJI, ACTION_KO


def render_result_card(result: dict, ms: int, payload: dict):
    """FDS 심사 결과 전체 렌더링."""
    r     = result["fds_result"]
    lvl   = r.get("risk_level", "SAFE")
    score = r.get("risk_score", 0)
    action_raw = r.get("action_taken", r.get("action", "APPROVE"))

    # ── 위험 등급 카드 ──
    css_cls = f"result-{lvl.lower()}"
    color   = RISK_COLOR.get(lvl, "#888")
    st.markdown(f"""
<div class="{css_cls}">
  <div style="display:flex; justify-content:space-between; align-items:center">
    <div>
      <span style="font-size:2rem; font-weight:700; color:{color}">
        {RISK_EMOJI.get(lvl,'')} {lvl}
      </span>
      <span style="margin-left:10px; font-size:0.9rem; color:#666">위험 등급</span>
    </div>
    <div style="text-align:right">
      <div style="font-size:1.4rem; font-weight:700">{score*100:.1f}%</div>
      <div style="font-size:0.75rem; color:#666">리스크 점수</div>
    </div>
  </div>
  <div style="margin-top:0.8rem; font-size:1rem; font-weight:600">
    {ACTION_KO.get(action_raw, action_raw)}
  </div>
  <div style="margin-top:0.4rem; font-size:0.85rem; color:#555">
    {r.get('reason','')}
  </div>
</div>
""", unsafe_allow_html=True)

    st.markdown("")

    # ── 리스크 게이지 ──
    _render_gauge(score, lvl)

    # ── 전문 상세 정보 ──
    _render_detail_expander(payload, ms, r)


def _render_gauge(score: float, lvl: str):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(score * 100, 1),
        domain={"x": [0, 1], "y": [0, 1]},
        title={"text": "리스크 점수 (%)", "font": {"size": 14}},
        gauge={
            "axis": {"range": [0, 100], "tickwidth": 1},
            "bar":  {"color": RISK_COLOR.get(lvl, "#888")},
            "steps": [
                {"range": [0,  10], "color": "#f0fdf4"},
                {"range": [10, 30], "color": "#f7fee7"},
                {"range": [30, 60], "color": "#fffbeb"},
                {"range": [60, 85], "color": "#fff7ed"},
                {"range": [85,100], "color": "#fef2f2"},
            ],
            "threshold": {
                "line": {"color": "red", "width": 2},
                "thickness": 0.75,
                "value": score * 100,
            },
        },
        number={"suffix": "%", "font": {"size": 28}},
    ))
    fig.update_layout(height=220, margin=dict(t=30, b=10, l=20, r=20))
    st.plotly_chart(fig, use_container_width=True)


def _render_detail_expander(payload: dict, ms: int, r: dict):
    with st.expander("📋 전문 상세 정보"):
        body  = payload["body"]
        sinfo = ACCOUNTS.get(body["sender"]["account_id"], {})
        rinfo = ACCOUNTS.get(body["receiver"]["account_id"], {})
        c1, c2 = st.columns(2)
        c1.markdown(f"**송금인:** {sinfo.get('name','?')}")
        c1.markdown(f"**계좌 등급:** {sinfo.get('grade','?')}")
        c1.markdown(f"**거래 전 잔액:** ₩{body['sender']['current_balance']:,}")
        c2.markdown(f"**수취인:** {rinfo.get('name','?')}")
        c2.markdown(f"**거래 유형:** {body['transaction_type']}")
        c2.markdown(f"**금액:** ₩{body['amount']:,}")
        st.markdown(f"**전문번호:** `{payload['header']['telegram_no']}`")
        st.markdown(f"**처리시간:** {ms}ms | **모델:** {r.get('model_version','v1')}")