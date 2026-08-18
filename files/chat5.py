"""
================================================================================
chat.py — 채팅 화면 + 흐름 제어 (플로우차트 전체 구현)
================================================================================

이 파일은 "화면"과 "흐름 제어"만 담당합니다. 판단(프롬프트)은 전부
services.py 안에 있습니다.

■ flow_state 값과 플로우차트 노드의 대응관계 (전체)
--------------------------------------------------------------------------------
  flow_state 값       플로우차트 노드                    다음에 실행할 함수
--------------------------------------------------------------------------------
  "scam_check"        사기 의심 여부 진단                classify_scam()
  "safe"              (안심 안내 완료. 재입력 오면        classify_scam() 재실행
                        다시 scam_check로 취급)
  "stage_check"        피해 단계 진단                     classify_stage()
  "guide_shown"         (단계별 가이드까지 표시 완료.       -
                        사용자가 "대응 도구"를 누르길 기다림)
  "tools_done"          (전화대본/리포트/체크리스트까지     -
                        모두 표시 완료. 대화 끝)
--------------------------------------------------------------------------------

■ 왜 "가이드 표시"와 "대응 도구 생성"을 버튼으로 분리했는가
    플로우차트를 보면 4가지 가이드 → 대응 도구 3종 → "사용자가 신고/상담에
    활용"으로 이어집니다. 이 전화대본/리포트/체크리스트 3개는 한 번에
    LLM을 3번 더 호출해야 하는 다소 무거운 작업이라, 가이드를 본 사용자가
    "네, 신고 준비할래요" 같은 의사를 표시했을 때만 실행하는 게 자연스럽고
    비용도 아낄 수 있습니다. 그래서 가이드 카드 아래에 버튼을 두어
    사용자가 원할 때 대응 도구를 생성하도록 만들었습니다.
    (원하시면 이 버튼 없이 자동으로 이어지게 바꿀 수도 있습니다 —
     이 파일 맨 아래 "대응 도구 생성" 섹션에서 조건만 바꾸면 됩니다.)
================================================================================
"""

import streamlit as st
from services import (
    classify_scam,
    classify_stage,
    guide_contact_early,
    guide_personal_info,
    guide_device_account,
    guide_financial_loss,
    generate_report_script,
    generate_damage_report,
    generate_evidence_checklist,
)

st.title("상황 진단")
st.caption("편하게 말씀해주세요. 판단하지 않고 같이 살펴볼게요.")

# -----------------------------------------------------------------------------
# stage(문자열) → 어떤 가이드 함수를 부를지 매핑
# -----------------------------------------------------------------------------
# classify_stage()가 돌려주는 "stage" 값과, services.py의 4개 가이드 함수를
# 딕셔너리로 연결해둡니다. 이렇게 해두면 아래 코드에서
# if stage == "접촉초기": guide_contact_early(...)
# elif stage == "개인정보제공": guide_personal_info(...)
# ... 이렇게 4줄 쓰는 대신 한 줄로 처리할 수 있습니다.
STAGE_TO_GUIDE_FN = {
    "접촉초기": guide_contact_early,
    "개인정보제공": guide_personal_info,
    "기기계정": guide_device_account,
    "금융피해": guide_financial_loss,
}

# -----------------------------------------------------------------------------
# 세션 상태 초기화
# -----------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []

if "flow_state" not in st.session_state:
    st.session_state.flow_state = "scam_check"

if "guide_data" not in st.session_state:
    st.session_state.guide_data = None

if "detected_stage" not in st.session_state:
    st.session_state.detected_stage = None

# 대응 도구(전화대본/리포트/체크리스트) 결과를 각각 저장
if "tool_script" not in st.session_state:
    st.session_state.tool_script = None
if "tool_report" not in st.session_state:
    st.session_state.tool_report = None
if "tool_checklist" not in st.session_state:
    st.session_state.tool_checklist = None


# -----------------------------------------------------------------------------
# 지금까지의 대화를 화면에 표시
# -----------------------------------------------------------------------------
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


def build_conversation_text() -> str:
    """session_state.messages(리스트)를 하나의 텍스트로 합칩니다."""
    lines = []
    for m in st.session_state.messages:
        speaker = "사용자" if m["role"] == "user" else "든든이"
        lines.append(f"{speaker}: {m['content']}")
    return "\n".join(lines)


# =============================================================================
# 사용자 입력 처리 (흐름 제어의 핵심부)
# =============================================================================
user_input = st.chat_input("메시지를 입력하세요")

if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})
    conversation_text = build_conversation_text()

    # =========================================================================
    # [A] flow_state가 "scam_check" 또는 "safe"
    #     → 플로우차트: 사기 의심 여부 진단
    # =========================================================================
    if st.session_state.flow_state in ["scam_check", "safe"]:
        result = classify_scam(conversation_text)

        if result["verdict"] == "insufficient":
            # → 근거 부족: 추가 질문하고 같은 단계에 머무름 (재입력 루프)
            st.session_state.messages.append(
                {"role": "assistant", "content": result["follow_up_question"]}
            )
            st.session_state.flow_state = "scam_check"

        elif result["verdict"] == "low_risk":
            # → 사기 가능성 낮음: 안심 안내
            st.session_state.messages.append(
                {"role": "assistant", "content": result["safe_message"]}
            )
            # "safe" 상태로 두면, 사용자가 다음에 또 입력했을 때
            # 위 if 조건에 다시 걸려서 classify_scam()이 재실행됩니다.
            st.session_state.flow_state = "safe"

        elif result["verdict"] == "suspected":
            # → 사기 의심: 피해 단계 진단으로 즉시 이동
            st.session_state.flow_state = "stage_check"
            stage_result = classify_stage(conversation_text)

            if not stage_result["has_enough_info"]:
                st.session_state.messages.append(
                    {"role": "assistant", "content": stage_result["follow_up_question"]}
                )
                # flow_state는 "stage_check" 유지 → 다음 입력은 [B]로 감
            else:
                st.session_state.detected_stage = stage_result["stage"]
                # 단계가 정해졌으니, 그 단계 전용 가이드 함수를 바로 호출
                guide_fn = STAGE_TO_GUIDE_FN[stage_result["stage"]]
                guide = guide_fn(conversation_text)
                st.session_state.guide_data = guide
                st.session_state.flow_state = "guide_shown"
                st.session_state.messages.append(
                    {"role": "assistant", "content": guide["summary"]}
                )

    # =========================================================================
    # [B] flow_state가 "stage_check"
    #     → 플로우차트: 피해 단계 진단의 "근거 부족 → 추가 질문 → 재진단" 루프
    # =========================================================================
    elif st.session_state.flow_state == "stage_check":
        stage_result = classify_stage(conversation_text)

        if not stage_result["has_enough_info"]:
            st.session_state.messages.append(
                {"role": "assistant", "content": stage_result["follow_up_question"]}
            )
            # flow_state 그대로 "stage_check" 유지 (계속 순환)
        else:
            st.session_state.detected_stage = stage_result["stage"]
            guide_fn = STAGE_TO_GUIDE_FN[stage_result["stage"]]
            guide = guide_fn(conversation_text)
            st.session_state.guide_data = guide
            st.session_state.flow_state = "guide_shown"
            st.session_state.messages.append(
                {"role": "assistant", "content": guide["summary"]}
            )

    # =========================================================================
    # [C] flow_state가 "guide_shown" 또는 "tools_done"
    #     → 이미 가이드(또는 도구)까지 나온 상태에서 새 메시지가 온 경우
    #     → 완전히 새로운 상황으로 보고 처음부터 다시 진단합니다.
    # =========================================================================
    elif st.session_state.flow_state in ["guide_shown", "tools_done"]:
        st.session_state.flow_state = "scam_check"
        st.session_state.guide_data = None
        st.session_state.detected_stage = None
        st.session_state.tool_script = None
        st.session_state.tool_report = None
        st.session_state.tool_checklist = None
        # 이번 입력은 재실행 후 위 [A]에서 처음부터 다시 처리됩니다.

    st.rerun()


# =============================================================================
# 가이드 카드 표시
# 플로우차트: 접촉초기/개인정보/기기계정/금융피해 대응 가이드 각각의 출력
# =============================================================================
if st.session_state.flow_state in ["guide_shown", "tools_done"] and st.session_state.guide_data:
    guide = st.session_state.guide_data
    with st.container(border=True):
        st.markdown(f"**{st.session_state.detected_stage} 단계 · 지금 하시면 좋은 것**")
        for i, action in enumerate(guide["priority_actions"], 1):
            st.markdown(f"{i}. {action}")
        st.caption(guide["explanation"])


# =============================================================================
# 대응 도구 제공
# 플로우차트: "대응 도구 제공" → 전화대본 / 리포트 / 체크리스트 3종
# =============================================================================
# 가이드가 나온 상태(guide_shown)에서만 이 섹션을 보여줍니다.
# 버튼을 누르면 3개 함수를 호출해서 각각 결과를 세션에 저장하고,
# 그 아래에서 순서대로 화면에 표시합니다.
if st.session_state.flow_state == "guide_shown":
    st.divider()
    st.markdown("**신고나 상담을 준비하고 싶으신가요?**")
    if st.button("신고/상담 준비 도구 만들기"):
        conversation_text = build_conversation_text()
        stage = st.session_state.detected_stage

        with st.spinner("준비하고 있어요..."):
            st.session_state.tool_script = generate_report_script(conversation_text, stage)
            st.session_state.tool_report = generate_damage_report(conversation_text, stage)
            st.session_state.tool_checklist = generate_evidence_checklist(conversation_text, stage)

        st.session_state.flow_state = "tools_done"
        st.rerun()

# 대응 도구 3종 결과 표시 (tools_done 상태일 때)
if st.session_state.flow_state == "tools_done":
    st.divider()
    st.markdown("### 신고/상담 준비 자료")

    # 1) 전화 대본
    if st.session_state.tool_script:
        with st.expander(st.session_state.tool_script["title"], expanded=True):
            for line in st.session_state.tool_script["script_lines"]:
                st.write(f"“{line}”")

    # 2) 피해 상황 요약 리포트
    if st.session_state.tool_report:
        report = st.session_state.tool_report
        with st.expander("피해 상황 요약 리포트", expanded=False):
            st.write(report["incident_summary"])
            st.markdown("**타임라인**")
            for t in report["timeline"]:
                st.markdown(f"- {t}")
            st.markdown("**상대방이 요구했던 것**")
            for r in report["requested_by_scammer"]:
                st.markdown(f"- {r}")
            st.markdown(f"**피해 금액**: {report['amount_lost']}")

    # 3) 증거 보존 체크리스트
    if st.session_state.tool_checklist:
        with st.expander("증거 보존 체크리스트", expanded=False):
            for item in st.session_state.tool_checklist["checklist"]:
                st.checkbox(item, key=f"chk_{item}")

    st.caption("이 자료들을 가지고 112 또는 금융기관에 신고/상담하시면 도움이 돼요.")
