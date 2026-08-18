import random

import streamlit as st

import mock_data as data
import services
from components import fmt, render_chat_message, render_risk_result

# --- 세션 초기화 ---
if "chat_log" not in st.session_state:
    st.session_state.chat_log = [{"role": "assistant", "content": data.CHAT_OPENING_MESSAGE}]
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "show_phone_script" not in st.session_state:
    st.session_state.show_phone_script = False
if "show_report" not in st.session_state:
    st.session_state.show_report = False


def _plain_history() -> list[dict]:
    return [{"role": e["role"], "content": e["content"]} for e in st.session_state.chat_log if "content" in e]


def handle_user_message(text: str) -> None:
    text = text.strip()
    if not text:
        return
    history_before = _plain_history()
    st.session_state.chat_log.append({"role": "user", "content": text})

    if services.contains_sensitive_info(text):
        st.session_state.chat_log.append({"role": "assistant", "content": data.SENSITIVE_INFO_WARNING})
        return

    with st.spinner(random.choice(data.LOADING_MESSAGES)):
        result = services.diagnose(text, history_before)

    st.session_state.chat_log.append({"role": "assistant", "result": result})
    st.session_state.last_result = result
    st.session_state.show_phone_script = False
    st.session_state.show_report = False
    if result.level == "damage":
        st.session_state.chat_log.append({"role": "assistant", "content": data.CARE_MESSAGE})


# --- 헤더 ---
header_col, reset_col = st.columns([5, 1])
with header_col:
    st.markdown('<div class="dj-headline" style="font-size:1.8rem;">💬 상황 진단</div>', unsafe_allow_html=True)
with reset_col:
    if st.button("🔄 새 상담", use_container_width=True):
        st.session_state.chat_log = [{"role": "assistant", "content": data.CHAT_OPENING_MESSAGE}]
        st.session_state.last_result = None
        st.session_state.show_phone_script = False
        st.session_state.show_report = False
        st.rerun()

# --- 홈/뉴스에서 넘어온 프리필 처리 ---
if st.session_state.get("prefill_chip"):
    prefill = st.session_state.pop("prefill_chip")
    handle_user_message(prefill)

# --- 대화 내역 렌더 ---
for entry in st.session_state.chat_log:
    if "result" in entry:
        render_risk_result(entry["result"])
        if entry["result"].followup_question:
            render_chat_message("assistant", entry["result"].followup_question)
    else:
        render_chat_message(entry["role"], entry["content"])

# --- 결과 액션 버튼 ---
if st.session_state.last_result is not None:
    result = st.session_state.last_result
    a2, a3 = st.columns(2)
    with a2:
        if st.button("📞 전화 대본 만들기", use_container_width=True):
            st.session_state.show_phone_script = not st.session_state.show_phone_script
    with a3:
        if st.button("📄 사건 요약 리포트 만들기", use_container_width=True):
            st.session_state.show_report = True

    if st.session_state.show_phone_script:
        script = services.generate_phone_script(result.fraud_type_id)
        with st.container():
            st.markdown('<div class="dj-card dj-card-white">', unsafe_allow_html=True)
            st.markdown("**📞 그대로 읽으시면 돼요**")
            st.caption(script["intro"])
            st.markdown(f'**첫 마디**: {fmt(script["opening"])}', unsafe_allow_html=True)
            st.markdown("**상대가 물어볼 것**")
            for q, a in script["expected_qna"]:
                st.markdown(f"- {q} → {a}")
            st.markdown("**꼭 요청할 것**: " + " / ".join(script["must_say"]))
            st.markdown("**통화 끝나고 받아적을 것**: " + " / ".join(script["after_call"]))
            st.markdown("</div>", unsafe_allow_html=True)

    if st.session_state.show_report:
        report_text = services.generate_case_report(_plain_history())
        st.download_button(
            "⬇️ 사건 요약 리포트 다운로드 (.md)",
            data=report_text,
            file_name="텅장지키미_상담요약.md",
            mime="text/markdown",
        )

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

# --- 입력창 (캡처/녹음 첨부는 입력창의 파일 아이콘으로) ---
user_input = st.chat_input(
    data.CHAT_INPUT_PLACEHOLDER,
    accept_file="multiple",
    file_type=["png", "jpg", "jpeg", "mp3", "m4a", "wav"],
)
if user_input:
    for uploaded in user_input.files:
        if (uploaded.type or "").startswith("image/"):
            st.session_state.chat_log.append({"role": "user", "content": f"📎 캡처 업로드: {uploaded.name}"})
            st.session_state.chat_log.append(
                {"role": "assistant", "content": "캡처 확인했어요! 지금은 화면 속 문구를 직접 채팅으로도 같이 알려주시면 더 정확하게 봐드릴 수 있어요."}
            )
        else:
            st.session_state.chat_log.append({"role": "user", "content": f"🎙 통화 녹음 업로드: {uploaded.name}"})
            st.session_state.chat_log.append(
                {"role": "assistant", "content": "녹음 확인했어요! 통화에서 상대가 뭐라고 했는지 짧게 요약해서 채팅으로 알려주시면 더 정확해요."}
            )
    if user_input.text:
        handle_user_message(user_input.text)
    st.rerun()
