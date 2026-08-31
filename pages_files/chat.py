"""상황 진단 챗봇 화면.

여기서는 화면 그리기와 단계 전환만 다룬다. 판단 로직은 전부 services.py에 있다.

대화 단계(st.session_state.chat_phase):

  collecting    시작 단계. 사용자 발화를 구조화하고 필수 필드가 비면 되묻는다.
                필드가 차거나 되묻기 상한에 걸리면 사례 검색을 돌리고,
                그 결과에 따라 아래 셋 중 하나로 넘어간다.
                                                    → collect_and_advance()

  confirming    Coverage 0.6~0.8. 확정하기엔 모자라 사용자에게 되묻는 단계다.
                후보 사례를 헤드라인·일치 축·공식 링크와 함께 보여주고
                "이거랑 비슷한가요"를 묻는다.
                예 → guided / 아니오 → insufficient

  detail_check  사기로 판단된 뒤, 피해 단계 진단에 필요한 정보를 채우는 단계.
                검색에는 필요 없어 판정 전에 묻지 않은 것들(이미 한 행동, 송금 방식)을
                여기서 묻는다. 4-B 로 빠질 사용자에게는 묻지 않는다.
                MAX_DETAIL_ROUNDS번까지 묻고 stage_check 로 넘어간다.

  stage_check   가이드를 내기 직전, 위험 신호와 판정된 피해 단계를 보여주고
                "이게 맞나요"를 묻는 단계. 가이드 내용이 피해 단계에 따라 통째로
                갈리므로 확정 전에 사용자와 맞춰 본다.
                맞다 → guided / 다르다(보충 설명) → 재구조화·재진단 후 다시 물음
                MAX_STAGE_CHECK_ROUNDS번을 넘기면 더 묻지 않고 사용자가 마지막에
                설명한 내용으로 진단해 guided 로 넘어간다.

  guided        사례가 확인된 종착점. 피해 단계별 가이드를 이미 냈고,
                화면 아래에 대응 도구 3종 버튼이 뜬다.
                리포트를 만들면 .md 다운로드 버튼이 추가된다.

  insufficient  사기로 단정하기 어려운 종착점. 어디에 확인하면 되는지를 냈고,
                화면 아래 '신고 전화 대본' 버튼으로 대본을 볼 수 있다.
                정상적인 절차를 밟은 사용자가 여기로 온다.

단계 전환 함수
  collect_and_advance()   ② 구조화 → 되묻기 또는 ③으로
  run_search()            ③ 검색 → Coverage 세 갈래
  go_to_detail_check()    ④ 진단용 정보 되묻기, phase=detail_check
  go_to_stage_check()     ④ 피해 단계 진단 → 사용자 확인 요청, phase=stage_check
  go_to_guide()           ⑤ 확정된 단계의 가이드, phase=guided
  go_to_agency_inquiry()  4-B 기관 문의 대본, phase=insufficient

화면에서 신경 쓴 것
  - 검색과 판정에 임베딩 1회 + LLM 1회가 들어가 한 턴이 5~10초 걸린다.
    단계별 문구를 넣은 스피너로 무엇을 하는 중인지 알린다.
  - 주민번호·인증번호가 섞인 입력은 구조화 전에 걸러 경고만 보낸다.
  - 첨부한 캡처·녹음은 파일명만 대화에 남긴다. 아직 내용을 읽지는 않는다.
  - API 키 누락과 통신 오류는 대화 흐름을 깨지 않고 안내 메시지로 대신한다.
"""

import requests
import streamlit as st

import mock_data as data
import services
from components import render_chat_message

CALL_SCRIPT_LABEL = "📞 신고 전화 대본"

TOOL_BUTTONS = [
    ("call_script", CALL_SCRIPT_LABEL),
    ("report", "📋 피해 상황 요약 리포트"),
    ("checklist", "🗂 증거 보존 체크리스트"),
]

CONNECTION_ERROR_MESSAGE = "지금 분석 서버 연결이 원활하지 않아요. 잠시 후 다시 시도해 주세요."
MISSING_API_KEY_MESSAGE = "UPSTAGE_API 환경변수가 설정되어 있지 않아요. 실행 터미널에서 키를 설정한 뒤 앱을 다시 시작해 주세요."
# 종착점(guided / insufficient)에서 더 들어온 발화에 대한 응답. 자유 질문에 답할
# 수단이 없으므로 질문을 유도하지 않는다. 이 서비스가 할 일은 기관으로 넘겨주는
# 데까지이고, 그 뒤는 기관이 맡는다.
CLOSING_MESSAGE = "이 상담은 여기까지예요. 새 상담 버튼을 눌러 다시 시작할 수 있어요."


def _reset_state() -> None:
    st.session_state.chat_phase = "collecting"
    st.session_state.chat_messages = [
        {"role": "assistant", "content": data.CHAT_OPENING_MESSAGE, "kind": "ask"}
    ]
    st.session_state.structured = {}
    st.session_state.follow_up_rounds = 0
    st.session_state.damage_stage = None
    st.session_state.detail_rounds = 0
    st.session_state.asked_detail_fields = set()
    st.session_state.stage_check_rounds = 0
    st.session_state.candidate = None
    st.session_state.search_results = []
    st.session_state.tool_outputs = {}
    st.session_state.inquiry_script = None


if "chat_phase" not in st.session_state:
    _reset_state()


def _history() -> list[dict]:
    """대화 전체. 가이드·도구·단계 분류가 맥락으로 쓴다."""
    return [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat_messages]


def _structuring_history() -> list[dict]:
    """구조화에 넘길 대화. 어시스턴트 쪽은 짧은 질문만 남긴다.

    인사말과 되묻기 질문은 추출을 돕는다 — 빼면 결과가 얇아져 검색 질의문이 약해진다
    (골든셋 #17에서 key_context가 통째로 비면서 recall이 실패했다). 반대로 위험 신호
    목록이나 가이드처럼 긴 생성물이 끼면 모델이 추출을 그만두고 빈 객체를 돌려준다.
    그래서 메시지를 쌓을 때 종류를 붙여 두고 여기서 가른다.
    """
    return [
        {"role": m["role"], "content": m["content"]}
        for m in st.session_state.chat_messages
        if m["role"] == "user" or m.get("kind") == "ask"
    ]


def append(role: str, content: str, kind: str = "out") -> None:
    """kind="ask" 는 구조화에 함께 넘길 짧은 질문. 생성물은 "out" 으로 둔다."""
    st.session_state.chat_messages.append({"role": role, "content": content, "kind": kind})


def reply(content: str, kind: str = "out") -> None:
    append("assistant", content, kind)


# --- 단계 전환 --------------------------------------------------------------


def collect_details() -> None:
    """진단에 필요한 정보를 채운다. 다 찼거나 상한에 걸리면 단계 확인으로 넘어간다.

    검색용 정보만으로는 '무엇을 이미 했는지'를 알 수 없다. 그 값이 피해 단계를 가르고
    단계가 가이드 전체를 가른다.

    한 번 물은 필드는 asked_detail_fields 에 남겨 다시 묻지 않는다. 이 단계는 빈칸이면
    묻기 때문에, "그런 건 없었어요"라는 답으로도 필드는 계속 비어 있다. 기억해 두지
    않으면 같은 질문이 라운드마다 되돌아온다.
    """
    st.session_state.structured = services.structure_situation(_structuring_history())
    asked = st.session_state.asked_detail_fields
    missing = services.missing_diagnosis_fields(st.session_state.structured, asked)

    if missing and st.session_state.detail_rounds < services.MAX_DETAIL_ROUNDS:
        st.session_state.detail_rounds += 1
        picked = missing[: services.MAX_FIELDS_PER_QUESTION]
        asked.update(picked)
        reply(services.ask_for(picked, services.ASK_HEAD_DETAIL), kind="ask")
        return
    go_to_stage_check()


def go_to_detail_check() -> None:
    """④ 사기로 판단된 직후. 진단용 정보를 먼저 채운다."""
    st.session_state.chat_phase = "detail_check"
    collect_details()


def go_to_stage_check() -> None:
    """④-A 피해 단계를 진단하고, 가이드를 내기 전에 사용자에게 맞는지 묻는다.

    구조화는 collect_details() 가 방금 끝냈으므로 다시 하지 않는다.
    """
    structured = st.session_state.structured
    stage = services.classify_damage_stage(structured)
    st.session_state.damage_stage = stage
    st.session_state.chat_phase = "stage_check"
    reply(services.make_stage_check(structured, st.session_state.search_results, stage))


def go_to_guide() -> None:
    """⑤ 확정된 피해 단계의 가이드를 낸다."""
    st.session_state.chat_phase = "guided"
    reply(services.make_guide(st.session_state.damage_stage, _history()))


def revise_stage_check() -> None:
    """사용자가 단계를 정정했을 때. 다시 진단해 되묻되, 상한을 넘기면 그대로 확정한다."""
    st.session_state.structured = services.structure_situation(_structuring_history())
    st.session_state.stage_check_rounds += 1
    if st.session_state.stage_check_rounds >= services.MAX_STAGE_CHECK_ROUNDS:
        # 더 묻지 않는다. 사용자가 마지막에 설명한 내용을 그대로 쓴다.
        st.session_state.damage_stage = (
            services.classify_damage_stage(st.session_state.structured) or "접촉초기"
        )
        go_to_guide()
        return
    go_to_stage_check()


def go_to_agency_inquiry() -> None:
    """④-B 사기로 단정할 수 없을 때. 어디에 확인하면 되는지를 낸다.

    전화 대본은 여기서 함께 받아 두기만 하고, 버튼을 눌렀을 때 내보낸다.
    LLM 호출은 이 한 번뿐이라 버튼을 눌러도 기다릴 일이 없다.
    """
    st.session_state.chat_phase = "insufficient"
    guide, script = services.make_agency_inquiry_script(st.session_state.structured)
    st.session_state.inquiry_script = script
    reply(guide)


def run_search() -> None:
    """② 사례를 검색하고 Coverage로 세 갈래를 탄다."""
    result = services.search_similar_cases(st.session_state.structured)
    decision = result["decision"]

    st.session_state.search_results = result["results"]

    if decision == "confirmed":
        go_to_detail_check()
    elif decision == "needs_confirm":
        st.session_state.candidate = result["results"][0]
        st.session_state.chat_phase = "confirming"
        reply(services.format_case_for_user(result["results"][0]))
    else:
        go_to_agency_inquiry()


def collect_and_advance() -> None:
    """① 대화를 구조화하고, 필수 필드가 차면 검색으로 넘어간다.

    되묻기는 MAX_FOLLOW_UP_ROUNDS번까지만 한다. 그 이상은 사용자를 지치게 하고,
    모자란 정보로도 검색은 돌아간다(대신 Coverage가 낮게 나와 ④-B로 빠진다).
    """
    st.session_state.structured = services.structure_situation(_structuring_history())
    missing = services.missing_required_fields(st.session_state.structured)

    if missing and st.session_state.follow_up_rounds < services.MAX_FOLLOW_UP_ROUNDS:
        st.session_state.follow_up_rounds += 1
        reply(services.ask_for(missing), kind="ask")
        return
    run_search()


# --- 예/아니오 해석 ---------------------------------------------------------

_YES_EXACT = {"y", "yes", "예", "예.", "네", "넵", "응", "ㅇ", "ㅇㅇ", "맞아", "맞아요", "그래", "그래요", "비슷", "비슷해요"}
_NO_EXACT = {"n", "no", "아니", "아니요", "아뇨", "아니야", "ㄴ", "ㄴㄴ", "달라요", "다릅니다", "아님", "아닌데요"}
_NO_PHRASES = ("아니", "아뇨", "달라", "다릅니다", "비슷하지 않", "해당 안", "아닌 것 같", "관련 없")
_YES_PHRASES = ("맞아", "맞습니다", "비슷", "그런 것 같", "네 ", "예 ")


def _interpret_yesno(text: str) -> str | None:
    """애매하면 None을 돌려 다시 묻게 한다."""
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


# --- 입력 처리 --------------------------------------------------------------

_SPINNER = {
    "collecting": "비슷한 사례를 찾아보고 있어요…",
    "confirming": "상황을 정리하고 있어요…",
    "detail_check": "확인하고 있어요…",
    "stage_check": "대응 방법을 정리하고 있어요…",
}


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
        with st.spinner(_SPINNER.get(phase, "확인하고 있어요…")):
            if phase == "collecting":
                collect_and_advance()

            elif phase == "confirming":
                answer = _interpret_yesno(text)
                if answer == "yes":
                    go_to_detail_check()
                elif answer == "no":
                    go_to_agency_inquiry()
                else:
                    reply("**예** 또는 **아니오**로 답해 주시면 이어서 안내할게요.", kind="ask")

            elif phase == "detail_check":
                collect_details()

            elif phase == "stage_check":
                # "맞아요"가 아니면 전부 정정으로 본다. 사용자가 덧붙인 설명이
                # 재진단의 근거가 되므로, 애매한 답도 되묻지 않고 그대로 넘긴다.
                if _interpret_yesno(text) == "yes":
                    go_to_guide()
                else:
                    revise_stage_check()

            else:  # guided, insufficient
                reply(CLOSING_MESSAGE)
    except services.MissingUpstageAPIError:
        reply(MISSING_API_KEY_MESSAGE)
    except requests.exceptions.RequestException:
        reply(CONNECTION_ERROR_MESSAGE)


IMAGE_EXT = ("png", "jpg", "jpeg")
AUDIO_EXT = ("mp3", "m4a", "wav")


def handle_uploaded_files(files) -> None:
    """채팅바에서 첨부한 캡처·녹음 처리. 파일 내용은 아직 읽지 않는다."""
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
        reply(reply_text, kind="ask")


# --- 화면 ------------------------------------------------------------------

header_col, reset_col = st.columns([5, 1])
with header_col:
    st.markdown('<div class="dj-headline" style="font-size:1.8rem;">💬 상황 진단</div>', unsafe_allow_html=True)
with reset_col:
    if st.button("🔄 새 상담", use_container_width=True):
        _reset_state()
        st.rerun()

# 홈/뉴스 카드에서 넘어온 프리필
if st.session_state.get("prefill_chip"):
    handle_user_message(st.session_state.pop("prefill_chip"))

for entry in st.session_state.chat_messages:
    render_chat_message(entry["role"], entry["content"])

# guided 단계에서만 대응 도구 3종을 노출한다
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

# insufficient 단계에서는 기관 문의 대본 하나만 노출한다. 이미 만들어 둔 문자열이라
# 눌러도 새로 부르지 않는다. 한 번 내보내면 대화에 남으므로 버튼은 감춘다.
if st.session_state.chat_phase == "insufficient" and st.session_state.get("inquiry_script"):
    if st.button(CALL_SCRIPT_LABEL, key="tool_inquiry_script", use_container_width=True):
        reply(f"**{CALL_SCRIPT_LABEL}**\n\n{st.session_state.inquiry_script}")
        st.session_state.inquiry_script = None
        st.rerun()

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)

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
