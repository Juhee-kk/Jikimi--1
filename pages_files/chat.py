import requests
import streamlit as st

import diagnose
import mock_data as data
import services
from components import render_chat_message

TOOL_BUTTONS = [
    ("call_script", "📞 신고 전화 대본"),
    ("report", "📋 피해 상황 요약 리포트"),
    ("checklist", "🗂 증거 보존 체크리스트"),
]

CONNECTION_ERROR_MESSAGE = "지금 분석 서버 연결이 원활하지 않아요. 잠시 후 다시 시도해 주세요."

TOOL_KEY_TO_FN = {
    "report": services.generate_damage_report,
    "checklist": services.generate_evidence_checklist,
}


# --- 세션 초기화 ---
def _reset_state() -> None:
    st.session_state.chat_phase = "suspicion"
    st.session_state.chat_messages = [{"role": "assistant", "content": data.CHAT_OPENING_MESSAGE}]
    st.session_state.ask_count = {"suspicion": 0, "damage_stage": 0}
    st.session_state.asked_stage_slots = set()
    st.session_state.damage_stage = None
    st.session_state.damage_stage_label = None
    st.session_state.signals = []
    st.session_state.guide_data = None
    st.session_state.tool_outputs = {}


if "chat_phase" not in st.session_state:
    _reset_state()


def _history() -> list[dict]:
    return [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat_messages]


def _user_text_blob() -> str:
    """diagnose()는 누적 텍스트 하나를 받으므로 지금까지의 user 발화를 전부 이어붙인다."""
    return " ".join(m["content"] for m in st.session_state.chat_messages if m["role"] == "user")


def append(role: str, content: str) -> None:
    st.session_state.chat_messages.append({"role": role, "content": content})


def reply(content: str) -> None:
    append("assistant", content)


def finish_with_guide(diagnosis: dict) -> None:
    st.session_state.damage_stage = diagnosis["damage_stage"]
    st.session_state.damage_stage_label = diagnosis["damage_stage_label"]
    st.session_state.chat_phase = "guided"
    # "공감_1문장"은 sections의 첫 항목으로 카드 안에 이미 렌더되므로 별도 채팅
    # 말풍선을 남기지 않는다 (중복 방지) — 카드 자체가 이번 턴의 응답이다.
    st.session_state.guide_data = services.build_guide(diagnosis, _history())


def _handle_damage_stage() -> None:
    """피해 단계 진단: 근거부족이면 diagnose.stage_followup()으로 되묻고,
    다 물어봤거나 단계가 확정되면 가이드로 넘어간다."""
    d = diagnose.diagnose(_user_text_blob())
    if d["damage_stage"] == "initial" and st.session_state.ask_count["damage_stage"] < 2:
        fu = diagnose.stage_followup(st.session_state.asked_stage_slots)
        if fu is None:
            finish_with_guide(d)  # 접촉초기로 확정
            return
        st.session_state.asked_stage_slots.add(fu["slot"])
        st.session_state.ask_count["damage_stage"] += 1
        reply(fu["question"])
    else:
        finish_with_guide(d)


def handle_user_message(text: str) -> None:
    text = text.strip()
    if not text:
        return
    append("user", text)

    if services.contains_sensitive_info(text):
        reply(data.SENSITIVE_INFO_WARNING)
        return

    phase = st.session_state.chat_phase
    if phase == "guided":
        # 새 메시지는 이전 상담과 무관한 새 상황일 가능성이 높음 — 이전 대화는
        # 비운 채로 완전히 새로운 진단을 시작한다.
        st.session_state.chat_messages = st.session_state.chat_messages[-1:]
        st.session_state.guide_data = None
        st.session_state.tool_outputs = {}
        st.session_state.damage_stage = None
        st.session_state.damage_stage_label = None
        st.session_state.ask_count = {"suspicion": 0, "damage_stage": 0}
        st.session_state.asked_stage_slots = set()
        st.session_state.chat_phase = "suspicion"
        phase = "suspicion"

    try:
        if phase == "suspicion":
            d = diagnose.diagnose(_user_text_blob())
            if d["verdict"] == "insufficient" and st.session_state.ask_count["suspicion"] < 2:
                st.session_state.ask_count["suspicion"] += 1
                reply(services.build_message(d, _history()))
            elif d["verdict"] == "unlikely":
                reply(services.build_message(d, _history()))
            else:  # suspected (근거부족 2회 초과 시에도 의심으로 진행: 안전 우선)
                st.session_state.chat_phase = "damage_stage"
                _handle_damage_stage()

        elif phase == "damage_stage":
            _handle_damage_stage()

    except requests.exceptions.RequestException:
        reply(CONNECTION_ERROR_MESSAGE)


def _format_damage_report(report: dict) -> str:
    lines = [report["incident_summary"], "", "**타임라인**"]
    lines += [f"- {t}" for t in report["timeline"]]
    lines += ["", "**상대방이 요구했던 것**"]
    lines += [f"- {r}" for r in report["requested_by_scammer"]]
    lines += ["", f"**피해 금액**: {report['amount_lost']}"]
    return "\n".join(lines)


def render_case_cards(cases: list[dict]) -> None:
    """유사사례 섹션 — Qdrant 연동 전까지는 항상 빈 리스트라 호출될 일 없지만,
    나중에 자리만 꽂으면 되도록 미리 만들어둔다."""
    for c in cases:
        with st.container(border=True):
            st.markdown(f"**{c['headline_ko']}**")
            st.caption(c["summary_ko"])


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
    st.markdown('<div class="dj-headline" style="font-size:1.8rem;">💬 상황 진단</div>', unsafe_allow_html=True)
with reset_col:
    if st.button("🔄 새 상담", use_container_width=True):
        _reset_state()
        st.rerun()

# --- 홈/뉴스에서 넘어온 프리필 처리 ---
if st.session_state.get("prefill_chip"):
    prefill = st.session_state.pop("prefill_chip")
    handle_user_message(prefill)

# --- 대화 내역 렌더 ---
for entry in st.session_state.chat_messages:
    render_chat_message(entry["role"], entry["content"])

# --- guided phase: 가이드 카드 (diagnosis["sections"] 순서 그대로 렌더) ---
if st.session_state.chat_phase == "guided" and st.session_state.guide_data:
    with st.container(border=True):
        st.markdown(f"**{st.session_state.damage_stage_label} · 지금 하시면 좋은 것**")
        for sec in st.session_state.guide_data["sections"]:
            if sec["key"] == "위험신호_근거":
                with st.expander("왜 위험하다고 봤는지", expanded=False):
                    for explain in sec["content"]:
                        st.markdown(f"- {explain}")
            elif sec["kind"] in ("text", "markdown"):
                st.markdown(sec["content"])
            elif sec["kind"] == "list":
                for item in sec["content"]:
                    st.markdown(f"- {item}")
            elif sec["kind"] == "cases":
                render_case_cards(sec["content"])
            # kind == "tools"는 아래 버튼 행에서 항상 렌더링되므로 여기선 스킵
        refund = st.session_state.guide_data["refund_eligible"]
        if refund is True:
            st.info("이 유형은 112 지급정지 대상이에요. 서두르세요.")
        elif refund is False:
            st.warning("이 유형은 통신사기피해환급법 적용 대상이 아니라 112 지급정지가 안 돼요. 형사고소·채권가압류 절차를 안내해드릴게요.")

# --- guided phase: 대응 도구 버튼 3개 ---
if st.session_state.chat_phase == "guided":
    tool_cols = st.columns(3)
    for col, (tool_key, label) in zip(tool_cols, TOOL_BUTTONS):
        with col:
            if st.button(label, key=f"tool_{tool_key}", use_container_width=True):
                try:
                    with st.spinner("작성 중이에요…"):
                        if tool_key == "call_script":
                            st.session_state.tool_outputs[tool_key] = services.generate_report_script(
                                st.session_state.damage_stage_label,
                                _history(),
                                refund_eligible=st.session_state.guide_data["refund_eligible"],
                            )
                        else:
                            st.session_state.tool_outputs[tool_key] = TOOL_KEY_TO_FN[tool_key](
                                st.session_state.damage_stage_label, _history()
                            )
                except requests.exceptions.RequestException:
                    reply(CONNECTION_ERROR_MESSAGE)
                st.rerun()

    if "call_script" in st.session_state.tool_outputs:
        out = st.session_state.tool_outputs["call_script"]
        with st.expander(out["title"], expanded=True):
            for line in out["script_lines"]:
                st.write(f"“{line}”")

    if "report" in st.session_state.tool_outputs:
        out = st.session_state.tool_outputs["report"]
        with st.expander("피해 상황 요약 리포트", expanded=False):
            st.write(out["incident_summary"])
            st.markdown("**타임라인**")
            for t in out["timeline"]:
                st.markdown(f"- {t}")
            st.markdown("**상대방이 요구했던 것**")
            for r in out["requested_by_scammer"]:
                st.markdown(f"- {r}")
            st.markdown(f"**피해 금액**: {out['amount_lost']}")
        st.download_button(
            "⬇️ 피해 상황 요약 리포트 다운로드 (.md)",
            data=_format_damage_report(out),
            file_name="텅장지키미_상담요약.md",
            mime="text/markdown",
        )

    if "checklist" in st.session_state.tool_outputs:
        out = st.session_state.tool_outputs["checklist"]
        with st.expander("증거 보존 체크리스트", expanded=False):
            for item in out["checklist"]:
                st.checkbox(item, key=f"chk_{item}")

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

# --- 입력창 (캡처/녹음 첨부는 입력창의 파일 아이콘으로) ---
submission = st.chat_input(
    data.CHAT_INPUT_PLACEHOLDER,
    accept_file="multiple",
    file_type=["png", "jpg", "jpeg", "mp3", "m4a", "wav"],
)

if submission:
    if submission.files:
        handle_uploaded_files(submission.files)
    if submission.text:
        handle_user_message(submission.text)
    st.rerun()