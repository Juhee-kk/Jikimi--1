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
MISSING_API_KEY_MESSAGE = "UPSTAGE_API 환경변수가 설정되어 있지 않아요. 실행 터미널에서 키를 설정한 뒤 앱을 다시 시작해 주세요."


# --- 세션 초기화 ---
# 대화 단계(chat_phase):
#   similarity   → 첫 사용자 입력을 유사도 DB 검색에 넣는다 (services.search_similar_cases, 미구현)
#   confirm      → 유사도가 낮아 '불확실'. 가장 유사한 사례를 보여주고 예/아니오를 기다린다
#   damage_stage → 피해 단계 분류 (LLM)
#   guided       → 대응 가이드 출력 완료. 대응 도구 3종 버튼 노출
#   self_check   → '불확실'에서 사용자가 '아니오' → 스스로 재확인 안내로 종료
def _reset_state() -> None:
    st.session_state.chat_phase = "similarity"
    st.session_state.chat_messages = [{"role": "assistant", "content": data.CHAT_OPENING_MESSAGE}]
    st.session_state.ask_count = {"damage_stage": 0}
    st.session_state.damage_stage = None
    st.session_state.similar_case = None
    st.session_state.user_modus_operandi = None
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


def advance_to_damage_stage() -> None:
    """피해 단계 분류를 돌리고, 결과에 따라 가이드로 넘기거나 한 번 더 되묻는다."""
    st.session_state.chat_phase = "damage_stage"
    s = services.classify_damage_stage(_history())
    if s["stage"] == "근거부족" and st.session_state.ask_count["damage_stage"] < 2:
        st.session_state.ask_count["damage_stage"] += 1
        reply("정확한 대응을 안내해 드리려고 하나만 확인할게요.\n\n" + s["follow_up"])
    else:
        stage = s["stage"] if s["stage"] != "근거부족" else "접촉초기"
        finish_with_guide(stage)


_YES_EXACT = {"y", "yes", "예", "예.", "네", "넵", "응", "ㅇ", "ㅇㅇ", "맞아", "맞아요", "그래", "그래요", "비슷", "비슷해요"}
_NO_EXACT = {"n", "no", "아니", "아니요", "아뇨", "아니야", "ㄴ", "ㄴㄴ", "달라요", "다릅니다", "아님", "아닌데요"}
_NO_PHRASES = ("아니", "아뇨", "달라", "다릅니다", "비슷하지 않", "해당 안", "아닌 것 같", "관련 없")
_YES_PHRASES = ("맞아", "맞습니다", "비슷", "그런 것 같", "네 ", "예 ")


def _interpret_yesno(text: str) -> str | None:
    """confirm 단계에서 사용자의 예/아니오 답을 해석. 애매하면 None(→ 다시 물어봄)."""
    t = text.strip().lower().rstrip(".!?~ ")
    if t in _YES_EXACT:
        return "yes"
    if t in _NO_EXACT:
        return "no"
    if any(k in t for k in _NO_PHRASES):   # 부정을 먼저 (예: "비슷하지 않아요")
        return "no"
    if any(k in t for k in _YES_PHRASES):
        return "yes"
    return None


def _format_similar_case(case: dict | None) -> str:
    if not case:
        return (
            "지금 상황과 비슷한 사례를 찾지는 못했어요. 그래도 확인이 필요해 보여요.\n\n"
            "혹시 상대가 돈·개인정보·앱 설치를 요구했나요? **예 / 아니오**로 답해 주세요."
        )
    lines = ["찾아본 것 중 지금 상황과 가장 비슷한 사례예요.", "", f"**{case.get('headline_ko') or '유사 사례'}**"]
    if case.get("summary_ko"):
        lines.append(case["summary_ko"])
    if case.get("modus_operandi_ko"):
        lines.append(f"\n- 수법: {case['modus_operandi_ko']}")
    if case.get("warning_signs"):
        lines.append("- 이런 말 나오면 의심: " + ", ".join(case["warning_signs"]))
    lines += ["", "지금 겪고 계신 상황이 이거랑 비슷한가요? **예 / 아니오**로 답해 주세요."]
    return "\n".join(lines)


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
        if phase == "similarity":
            # 사용자 상황을 한 줄로 구조화 → 유사도 DB 검색(질의문으로 사용) [검색은 미구현 스텁]
            st.session_state.user_modus_operandi = services.extract_user_modus_operandi(_history())
            result = services.search_similar_cases(st.session_state.user_modus_operandi)
            if services.is_fraud_certain(result["similarity"]):
                advance_to_damage_stage()  # 사기 확실 → 피해 단계 진단
            else:
                st.session_state.similar_case = result["case"]
                st.session_state.chat_phase = "confirm"
                reply(_format_similar_case(result["case"]))

        elif phase == "confirm":
            answer = _interpret_yesno(text)
            if answer == "yes":
                advance_to_damage_stage()
            elif answer == "no":
                st.session_state.chat_phase = "self_check"
                reply(services.make_self_check(st.session_state.user_modus_operandi))
            else:
                reply("**예** 또는 **아니오**로 답해 주시면 이어서 안내할게요.")

        elif phase == "damage_stage":
            advance_to_damage_stage()

        elif phase in ("guided", "self_check"):
            reply("추가로 궁금한 점이 있으면 편하게 말씀해 주세요. 새로운 상담은 위의 '새 상담' 버튼을 눌러주세요.")
    except services.MissingUpstageAPIError:
        reply(MISSING_API_KEY_MESSAGE)
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
                except services.MissingUpstageAPIError:
                    reply(MISSING_API_KEY_MESSAGE)
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
