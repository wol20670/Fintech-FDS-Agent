"""
세션 상태 관리 및 거래 전문(Payload) 생성 헬퍼
"""

import streamlit as st
from datetime import datetime
from .constants import ACCOUNTS


def init_session():
    defaults = {
        "sim_logs":    [],
        "tx_counter":  9000,
        "last_result": None,
        "sel_sender":   "C1000000001",
        "sel_receiver": "M2000000001",
        "sel_tx_type":  "TRANSFER",
        "sel_channel":  "MB",
        "inp_amount":   50_000,
        "inp_cnt":      1,
        "new_device":   False,
        "new_receiver": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


def apply_scenario(params: dict):
    st.session_state["sel_sender"]   = params["sender"]
    st.session_state["sel_receiver"] = params["receiver"]
    st.session_state["sel_tx_type"]  = params["tx_type"]
    st.session_state["sel_channel"]  = params["channel"]
    st.session_state["inp_amount"]   = params["amount"]
    st.session_state["inp_cnt"]      = params["cnt_1h"]
    st.session_state["new_device"]   = params["new_device"]
    st.session_state["new_receiver"] = params["new_receiver"]


def build_payload(sender_id, receiver_id, tx_type,
                  amount, channel, new_device, new_receiver, cnt_1h) -> dict:
    st.session_state.tx_counter += 1
    tno      = f"2026{channel}{st.session_state.tx_counter:010d}"
    sender   = ACCOUNTS[sender_id]
    receiver = ACCOUNTS[receiver_id]
    return {
        "header": {
            "telegram_no":      tno,
            "channel_code":     channel,
            "terminal_id":      f"TERM-{channel}-SIM",
            "institution_code": "088",
        },
        "body": {
            "transaction_type": tx_type,
            "amount":           amount,
            "sender": {
                "account_id":      sender_id,
                "account_type":    sender["type"],
                "current_balance": sender["balance"],
            },
            "receiver": {
                "account_id":      receiver_id,
                "account_type":    receiver["type"],
                "current_balance": receiver["balance"],
            },
        },
        "fds_metadata": {
            "tx_count_1h":     cnt_1h,
            "tx_count_24h":    cnt_1h * 3,
            "is_new_device":   new_device,
            "is_new_receiver": new_receiver,
        },
    }


def add_log(payload: dict, result: dict | None, ms: int):
    body   = payload["body"]
    sender = ACCOUNTS.get(body["sender"]["account_id"], {})
    recv   = ACCOUNTS.get(body["receiver"]["account_id"], {})

    if result:
        r = result["fds_result"]
        entry = {
            "시각":     datetime.now().strftime("%H:%M:%S"),
            "송금인":   sender.get("name", "?"),
            "수취인":   recv.get("name", "?"),
            "거래유형": body["transaction_type"],
            "금액":     body["amount"],
            "위험등급": r.get("risk_level", "?"),
            "조치":     r.get("action_taken", r.get("action", "?")),
            "점수":     round(r.get("risk_score", 0) * 100, 1),
            "응답(ms)": ms,
        }
    else:
        entry = {
            "시각":     datetime.now().strftime("%H:%M:%S"),
            "송금인":   sender.get("name", "?"),
            "수취인":   recv.get("name", "?"),
            "거래유형": body["transaction_type"],
            "금액":     body["amount"],
            "위험등급": "ERROR",
            "조치":     "오류",
            "점수":     0,
            "응답(ms)": ms,
        }

    st.session_state.sim_logs.insert(0, entry)
    if len(st.session_state.sim_logs) > 50:
        st.session_state.sim_logs = st.session_state.sim_logs[:50]