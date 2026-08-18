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


IMAGE_EXT = ("png", "jpg", "jpeg")
AUDIO_EXT = ("mp3", "m4a", "wav")


def handle_uploaded_files(files) -> None:
    """채팅바에서 첨부한 캡처·녹음 처리."""
    for f in files:
        ext = f.name.rsplit(".", 1)[-1].lower()
        if ext in IMAGE_EXT:
            icon, kind, reply = "📎", "캡처", (
                "캡처 확인했어요. 화면 속 문구를 채팅으로도 같이 알려주시면 더 정확하게 봐드릴 수 있어요."
            )
        elif ext in AUDIO_EXT:
            icon, kind, reply = "🎙", "통화 녹음", (
                "녹음 확인했어요. 통화에서 상대가 뭐라고 했는지 짧게 요약해 주시면 더 정확해요."
            )
        else:
            icon, kind, reply = "📄", "파일", "파일 확인했어요."
        st.session_state.chat_log.append({"role": "user", "content": f"{icon} {kind} 첨부: {f.name}"})
        st.session_state.chat_log.append({"role": "assistant", "content": reply})


# --- 헤더 ---
header_col, reset_col = st.columns([5, 1])
with header_col:
    st.markdown(
        '''<div class="dj-eyebrow">상담</div>
        <div class="dj-headline" style="font-size:1.85rem; margin-top:0.25rem;">상황 진단</div>''',
        unsafe_allow_html=True,
    )
with reset_col:
    if st.button("새 상담", use_container_width=True):
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
        if st.button("전화 대본 만들기", use_container_width=True):
            st.session_state.show_phone_script = not st.session_state.show_phone_script
    with a3:
        if st.button("사건 요약 리포트", use_container_width=True):
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

# --- 빠른 시작 칩 (대화 초반에만 노출) ---
if len(st.session_state.chat_log) <= 1:
    st.caption("어떤 상황인지 눌러주세요. 직접 쓰셔도 돼요.")

    rows = [data.QUICK_START_CHIPS[i : i + 3] for i in range(0, len(data.QUICK_START_CHIPS), 3)]
    for row in rows:
        cols = st.columns(len(row))
        for col, chip in zip(cols, row):
            with col:
                if st.button(chip, key=f"chip_{chip}", use_container_width=True):
                    handle_user_message(chip)
                    st.rerun()

    with st.expander(data.QUICK_START_MORE_LABEL):
        more_cols = st.columns(len(data.QUICK_START_CHIPS_MORE))
        for col, chip in zip(more_cols, data.QUICK_START_CHIPS_MORE):
            with col:
                if st.button(chip, key=f"chip_more_{chip}", use_container_width=True):
                    handle_user_message(chip)
                    st.rerun()

    st.caption(f"📎 {data.UPLOAD_HINT}")

# --- 입력창 ---
submission = st.chat_input(
    data.CHAT_INPUT_PLACEHOLDER,
    accept_file="multiple",
    file_type=["png", "jpg", "jpeg", "mp3", "m4a", "wav"],
)

if submission:
    files = getattr(submission, "files", None) or []
    text = (getattr(submission, "text", None) or "").strip()

    if files:
        handle_uploaded_files(files)
    if text:
        handle_user_message(text)
    st.rerun()