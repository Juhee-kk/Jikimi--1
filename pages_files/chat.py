import requests
import streamlit as st

import mock_data as data
import services
from components import render_chat_message

TOOL_BUTTONS = [
    ("call_script", "📞 신고 전화 대본"),
    ("report", "📋 피해 상황 요약 리포트"),
    ("checklist", "🗂 증거 보존 체크리스트"),
]

CONNECTION_ERROR_MESSAGE = "지금 분석 서버 연결이 원활하지 않아요. 잠시 후 다시 시도해 주세요."


# --- 세션 초기화 ---
def _reset_state() -> None:
    st.session_state.chat_phase = "suspicion"
    st.session_state.chat_messages = [{"role": "assistant", "content": data.CHAT_OPENING_MESSAGE}]
    st.session_state.ask_count = {"suspicion": 0, "damage_stage": 0}
    st.session_state.damage_stage = None
    st.session_state.signals = []
    st.session_state.tool_outputs = {}


if "chat_phase" not in st.session_state:
    _reset_state()


def _history() -> list[dict]:
    return [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat_messages]


def append(role: str, content: str) -> None:
    st.session_state.chat_messages.append({"role": role, "content": content})


def reply(content: str) -> None:
    append("assistant", content)


def finish_with_guide(stage: str) -> None:
    st.session_state.damage_stage = stage
    st.session_state.chat_phase = "guided"
    reply(services.make_guide(stage, _history()))


def handle_user_message(text: str) -> None:
    text = text.strip()
    if not text:
        return
    append("user", text)

    if services.contains_sensitive_info(text):
        reply(data.SENSITIVE_INFO_WARNING)
        return

    phase = st.session_state.chat_phase
    try:
        if phase == "suspicion":
            r = services.classify_suspicion(_history())
            if r["label"] == "근거부족" and st.session_state.ask_count["suspicion"] < 2:
                st.session_state.ask_count["suspicion"] += 1
                reply(r["follow_up"])
            elif r["label"] == "낮음":
                reply(
                    "현재 내용만으로는 사기 가능성이 낮아 보여요. 다만 앞으로 "
                    "개인정보·입금·링크 클릭을 요구받으면 꼭 다시 확인해 주세요!"
                )
            else:  # 의심 (근거부족 2회 초과 시에도 의심으로 진행: 안전 우선)
                st.session_state.signals += r.get("signals", [])
                st.session_state.chat_phase = "damage_stage"
                s = services.classify_damage_stage(_history())
                if s["stage"] == "근거부족":
                    st.session_state.ask_count["damage_stage"] += 1
                    reply(
                        "몇 가지 위험 신호가 보여요. 정확한 대응을 안내해 드리기 위해 "
                        "하나만 확인할게요.\n\n" + s["follow_up"]
                    )
                else:
                    finish_with_guide(s["stage"])

        elif phase == "damage_stage":
            s = services.classify_damage_stage(_history())
            if s["stage"] == "근거부족" and st.session_state.ask_count["damage_stage"] < 2:
                st.session_state.ask_count["damage_stage"] += 1
                reply(s["follow_up"])
            else:
                stage = s["stage"] if s["stage"] != "근거부족" else "접촉초기"
                finish_with_guide(stage)

        elif phase == "guided":
            reply("추가로 궁금한 점이 있으면 편하게 말씀해 주세요. 새로운 상담은 위의 '새 상담' 버튼을 눌러주세요.")
    except requests.exceptions.RequestException:
        reply(CONNECTION_ERROR_MESSAGE)


IMAGE_EXT = ("png", "jpg", "jpeg")
AUDIO_EXT = ("mp3", "m4a", "wav")


def handle_uploaded_files(files) -> None:
    """채팅바에서 첨부한 캡처·녹음 처리."""
    for f in files:
        ext = f.name.rsplit(".", 1)[-1].lower()
        if ext in IMAGE_EXT:
            icon, kind, reply_text = "📎", "캡처", (
                "캡처 확인했어요. 화면 속 문구를 채팅으로도 같이 알려주시면 더 정확하게 봐드릴 수 있어요."
            )
        elif ext in AUDIO_EXT:
            icon, kind, reply_text = "🎙", "통화 녹음", (
                "녹음 확인했어요. 통화에서 상대가 뭐라고 했는지 짧게 요약해 주시면 더 정확해요."
            )
        else:
            icon, kind, reply_text = "📄", "파일", "파일 확인했어요."
        append("user", f"{icon} {kind} 첨부: {f.name}")
        reply(reply_text)


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
        _reset_state()
        st.rerun()

# --- 홈/뉴스에서 넘어온 프리필 처리 ---
if st.session_state.get("prefill_chip"):
    prefill = st.session_state.pop("prefill_chip")
    handle_user_message(prefill)

# --- 대화 내역 렌더 ---
for entry in st.session_state.chat_messages:
    render_chat_message(entry["role"], entry["content"])

# --- guided phase: 대응 도구 버튼 3개 ---
if st.session_state.chat_phase == "guided":
    tool_cols = st.columns(3)
    for col, (tool_key, label) in zip(tool_cols, TOOL_BUTTONS):
        with col:
            if st.button(label, key=f"tool_{tool_key}", use_container_width=True):
                try:
                    with st.spinner("작성 중이에요…"):
                        output = services.make_tool(tool_key, st.session_state.damage_stage, _history())
                    st.session_state.tool_outputs[tool_key] = output
                    reply(f"**{label}**\n\n{output}")
                except requests.exceptions.RequestException:
                    reply(CONNECTION_ERROR_MESSAGE)
                st.rerun()

    if "report" in st.session_state.tool_outputs:
        st.download_button(
            "⬇️ 피해 상황 요약 리포트 다운로드 (.md)",
            data=st.session_state.tool_outputs["report"],
            file_name="텅장지키미_상담요약.md",
            mime="text/markdown",
        )

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

# --- 빠른 시작 칩 (대화 초반에만 노출) ---
if len(st.session_state.chat_messages) <= 1:
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
