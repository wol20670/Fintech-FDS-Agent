"""
거래 심사 탭
- 송금인/수취인/거래 파라미터 폼
- FDS 심사 실행 버튼
- 결과 카드 렌더링
"""

import streamlit as st
from utils import ACCOUNTS, GRADE_EMOJI, GRADE_KO, build_payload, call_evaluate, add_log
from components.result_card import render_result_card


def render(server_ok: bool):
    col_form, col_result = st.columns([1, 1], gap="large")

    with col_form:
        st.markdown("#### 거래 파라미터 설정")
        _render_form(server_ok)

    with col_result:
        st.markdown("#### 심사 결과")
        _render_result()


# ── 폼 ──

def _render_form(server_ok: bool):
    # 송금인
    sender_options = {
        k: f"{GRADE_EMOJI[v['grade']]} {v['name']} ({k[:8]}…) | ₩{v['balance']:,}"
        for k, v in ACCOUNTS.items() if v["type"] == "C"
    }
    sender_id = st.selectbox(
        "송금 계좌",
        options=list(sender_options.keys()),
        format_func=lambda x: sender_options[x],
        key="sel_sender",
    )

    # 수취인 (자기 자신 제외)
    recv_options = {
        k: f"{'🏪' if v['type']=='M' else '👤'} {v['name']} ({k[:8]}…)"
        for k, v in ACCOUNTS.items() if k != sender_id
    }
    # 현재 sel_receiver 값이 선택지에 없으면 첫 번째로 초기화
    if st.session_state.get("sel_receiver") not in recv_options:
        st.session_state["sel_receiver"] = list(recv_options.keys())[0]

    receiver_id = st.selectbox(
        "수취 계좌",
        options=list(recv_options.keys()),
        format_func=lambda x: recv_options[x],
        key="sel_receiver",
    )

    c1, c2 = st.columns(2)
    with c1:
        tx_type = st.selectbox(
            "거래 유형",
            ["TRANSFER", "CASH_OUT", "PAYMENT", "CASH_IN", "DEBIT"],
            key="sel_tx_type",
        )
    with c2:
        channel = st.selectbox("채널", ["MB", "IB", "AT", "TL"], key="sel_channel")

    amount = st.number_input(
        "거래 금액 (₩)",
        min_value=1_000, max_value=100_000_000,
        step=10_000, format="%d",
        key="inp_amount",
    )

    # 잔액 대비 프로그레스 바
    bal = ACCOUNTS[sender_id]["balance"]
    ratio = min(amount / bal, 1.0) if bal > 0 else 0
    st.progress(ratio, text=f"잔액 대비 {ratio*100:.1f}% (잔액: ₩{bal:,})")

    c3, c4 = st.columns(2)
    with c3:
        st.toggle("신규 기기",   key="new_device")
        st.toggle("신규 수취인", key="new_receiver")
    with c4:
        cnt_1h = st.number_input("1시간 내 거래 건수", 0, 50, key="inp_cnt")

    st.markdown("")

    # 심사 실행 버튼
    if st.button("🔍 FDS 심사 실행", type="primary",
                 use_container_width=True, disabled=not server_ok):
        payload = build_payload(
            sender_id, receiver_id, tx_type, amount, channel,
            st.session_state["new_device"],
            st.session_state["new_receiver"],
            st.session_state["inp_cnt"],
        )
        with st.spinner("FDS 모델 추론 중..."):
            result, ms, error = call_evaluate(payload)

        add_log(payload, result, ms)
        st.session_state.last_result = (result, ms, error, payload)
        st.rerun()

    if not server_ok:
        st.warning("⚠️ 서버를 먼저 실행하세요: `uvicorn main:app --reload --port 8000`")


# ── 결과 패널 ──

def _render_result():
    if st.session_state.last_result is None:
        st.info(
            "왼쪽에서 파라미터를 설정하고 **FDS 심사 실행** 버튼을 누르세요.\n\n"
            "또는 사이드바의 **빠른 시나리오**를 선택해 보세요."
        )
        return

    result, ms, error, payload = st.session_state.last_result

    if error:
        st.error(f"오류 발생: {error}")
    elif result:
        render_result_card(result, ms, payload)