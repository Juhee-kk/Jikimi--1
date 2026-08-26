"""LLM 호출 / 대응 가이드·도구 생성.

Upstage Solar Pro(solar-pro4)를 OpenAI 호환 chat completions 형식으로 호출한다.

판정(사기 의심 여부·피해 단계)은 diagnose.py의 결정론적 규칙 엔진이 담당한다 —
"판정은 규칙이, 문장은 LLM이" 원칙. 이 파일의 LLM 호출은 이미 확정된 판정 결과를
문장으로 풀어내는 역할(공감 인트로)과, 사용자가 버튼을 눌렀을 때만 생성하는
대응 도구 3종으로 한정된다.

플로우차트 노드 → 함수 대응:
  사기 의심 여부 진단 / 피해 단계 진단  → diagnose.diagnose() (규칙 엔진, 이 파일 아님)
  각 단계별 대응 가이드                → build_guide()
  신고용 전화 대본 만들기               → generate_report_script()
  피해 상황 요약 리포트                 → generate_damage_report()
  증거 보존 체크리스트                  → generate_evidence_checklist()

가이드는 guide_data.GUIDE_TEMPLATES의 고정 템플릿(행동 지침·기관명·연락처)을
그대로 사용한다. LLM은 공감 인트로(summary)만 생성한다 — 전화번호·URL 같은
사실 정보를 LLM이 지어내지 않도록 하기 위함.
"""

from __future__ import annotations

import json
import re

import requests
import streamlit as st

import guide_data

UPSTAGE_URL = "https://api.upstage.ai/v1/chat/completions"
MODEL = "solar-pro4"


def contains_sensitive_info(text: str) -> bool:
    """주민번호 패턴이나 비밀번호/인증번호 + 숫자 조합이 보이면 True."""
    if re.search(r"\d{6}-?\d{7}", text):
        return True
    if any(k in text for k in ("비밀번호", "인증번호", "otp", "OTP")) and re.search(r"\d{4,}", text):
        return True
    return False


def call_llm(system: str, messages: list[dict], temperature: float = 0.3) -> str:
    api_key = st.secrets["UPSTAGE_API_KEY"]
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}] + messages,
        "temperature": temperature,
    }
    r = requests.post(
        UPSTAGE_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json=payload,
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


def parse_json_safe(text: str, fallback: dict) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return fallback
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return fallback


# ---------------------------------------------------------------------------
# 1) 섹션 렌더링 — signals.json의 response_sections/section_spec을 따른다.
# ---------------------------------------------------------------------------
# diagnose()가 verdict×stage에 맞는 섹션 key 순서를 diagnosis["sections"]로 이미
# 계산해 돌려준다. 이 파일은 그 순서를 그대로 순회하며 각 섹션의 콘텐츠를 채울 뿐,
# 순서나 구성 자체를 바꾸지 않는다 — signals.json이 바뀌면 코드 수정 없이 반영된다.
# LLM은 "공감_1문장" 섹션 하나만 생성한다. 나머지는 matched_signals[].explain,
# guide_data.GUIDE_TEMPLATES, FOLLOWUP의 reason/question, 고정 문구를 그대로 쓴다 —
# LLM이 사실 정보를 지어내지 않도록 하기 위한 안전장치.

EMPATHY_SYSTEM = """너는 청년층 금융사기 대응을 돕는 AI 상담사 "든든이"야. 판단하지 않는다 —
아래는 이미 규칙 엔진이 확정한 결과다. 이걸 사용자 상황에 맞는 공감 문장으로만 풀어내라.

- verdict, matched_signals, stage는 이미 확정됐다. 다시 판단하거나 바꾸지 마라.
- 위험신호 설명을 새로 지어내지 마라 (그건 별도로 그대로 노출된다).
- 사용자를 탓하는 표현 금지. "당황스러우셨겠어요" 같은 톤.
- 공감 문장은 1~2문장만. 감정 반영 반복 금지. 이어서 안내가 나오므로 행동 지시는 쓰지 마라.

【 상황 】
{situation}
"""


def _situation_text(diagnosis: dict) -> str:
    signal_labels = ", ".join(s["label"] for s in diagnosis["matched_signals"]) or "없음"
    if diagnosis["verdict"] == "suspected":
        return (
            f"피해 단계: {diagnosis['damage_stage_label']} ({diagnosis['stage_headline']})\n"
            f"감지된 위험 신호: {signal_labels}"
        )
    return f"아직 판정에 필요한 정보가 부족한 상태.\n감지된 위험 신호: {signal_labels}"


def search_similar_cases(diagnosis: dict) -> list[dict]:
    """category_hints/scenario_hints로 Qdrant 유사사례를 검색한다.
    접속 정보·수집 파이프라인 코드를 아직 못 받아 스텁 상태 — 항상 빈 리스트.
    실제 연동 시 이 함수만 채우면 된다 (반환 형식은 case_db_schema 참고:
    headline_ko/summary_ko/severity_score 등)."""
    return []


def _section_content(key: str, diagnosis: dict, chat_messages: list[dict]) -> tuple[str, object] | None:
    """섹션 key 하나의 (kind, content)를 계산한다. 콘텐츠가 없으면 None → 섹션 생략."""
    if key == "공감_1문장":
        system = EMPATHY_SYSTEM.format(situation=_situation_text(diagnosis))
        return "text", call_llm(system, chat_messages, temperature=0).strip()
    if key == "위험신호_근거":
        explains = [s["explain"] for s in diagnosis["matched_signals"]]
        return ("list", explains) if explains else None
    if key.startswith("즉시조치_"):
        return "markdown", guide_data.GUIDE_TEMPLATES[diagnosis["damage_stage"]]
    if key == "유사사례":
        cases = search_similar_cases(diagnosis)
        return ("cases", cases) if cases else None
    if key == "단계확인_질문":
        label = diagnosis["damage_stage_label"]
        return "text", f"지금 상황이 **{label}** 단계로 보이는데, 맞으신가요? 다르면 편하게 알려주세요."
    if key == "대응도구":
        return "tools", None
    if key == "현재판단_보류명시":
        return "text", "지금 정보로는 확정할 수 없어요."
    if key == "부족한근거_설명":
        reasons = [f["reason"] for f in diagnosis["followups"]]
        return ("list", reasons) if reasons else None
    if key == "보충질문_최대2개":
        qs = [f["question"] for f in diagnosis["followups"]]
        return ("list", qs) if qs else None
    if key == "임시권고_보류":
        return "text", "확정되기 전까지는 송금이나 개인정보 제공은 잠시 미뤄주세요."
    if key == "안심_안내":
        return "text", "지금 내용만으로는 사기 가능성이 낮아 보여요."
    if key == "판단근거_설명":
        explains = [c["explain"] for c in diagnosis["calming_signals"]]
        return ("list", explains) if explains else None
    if key == "그래도확인할점":
        return None  # 카테고리별 확인사항 콘텐츠 미보유 — 저작되면 채울 자리
    if key == "재문의_안내":
        return "text", "개인정보·입금·링크 클릭을 요구받으면 다시 확인해보세요."
    return None


def build_guide(diagnosis: dict, chat_messages: list[dict]) -> dict:
    """suspected 최종 가이드 카드용 — 위젯(expander/버튼) 렌더링을 위해 구조화된
    섹션 리스트를 diagnosis["sections"] 순서 그대로 반환한다."""
    sections = []
    for key in diagnosis["sections"]:
        result = _section_content(key, diagnosis, chat_messages)
        if result is None:
            continue
        kind, content = result
        sections.append({"key": key, "kind": kind, "content": content})
    return {"sections": sections, "refund_eligible": diagnosis["refund_eligible"]}


def build_message(diagnosis: dict, chat_messages: list[dict]) -> str:
    """insufficient/unlikely용 — 채팅 말풍선 하나에 다 들어가야 하므로 섹션들을
    diagnosis["sections"] 순서 그대로 마크다운 텍스트 한 덩어리로 이어붙인다."""
    lines = []
    for key in diagnosis["sections"]:
        result = _section_content(key, diagnosis, chat_messages)
        if result is None:
            continue
        kind, content = result
        if kind in ("text", "markdown"):
            lines.append(content)
        elif kind == "list":
            lines.extend(f"- {c}" for c in content)
    return "\n\n".join(lines)


# ---------------------------------------------------------------------------
# 2) 대응 도구 3종 — 버튼 클릭 시에만 생성
# ---------------------------------------------------------------------------

REPORT_SCRIPT_SYSTEM = """
너는 청년층 금융사기 대응을 돕는 AI 상담사 "든든이"야.
사용자가 금융기관 또는 경찰(112)에 전화로 신고/상담할 때 그대로 읽을 수 있는
전화 대본을 만들어줘. 사용자의 피해 단계는 "{stage}"야.
{refund_note}

【 대본 작성 원칙 】
- 사용자가 당황한 상태에서도 그대로 읽으면 되도록, 실제 말하는 문장으로 작성
- 상담원이 물어볼 만한 정보(발생 일시, 금액, 상대방 연락처/계좌 등)를
  대화 내용에서 찾아 최대한 채워 넣고, 모르는 부분은 "확인 후 말씀드리겠습니다"로 처리
- 너무 길지 않게, 핵심만

【 응답 형식 - JSON만, 다른 텍스트 금지 】
{{
  "title": "전화 대본 제목 (예: 지급정지 신청 전화 대본)",
  "script_lines": ["실제로 말할 문장 1", "문장 2", "..."]
}}
"""

REFUND_ELIGIBLE_NOTE = "이 유형은 통신사기피해환급법 적용 대상이라 112 지급정지 신청이 가능해. 대본에 지급정지 요청을 포함해."
REFUND_INELIGIBLE_NOTE = "이 유형은 통신사기피해환급법 적용 대상이 아니라 112 지급정지가 안 돼. 형사고소·채권가압류 절차 안내로 대본을 작성해."

DAMAGE_REPORT_SYSTEM = """
너는 청년층 금융사기 대응을 돕는 AI 상담사 "든든이"야.
지금까지의 대화 내용을 바탕으로, 신고나 상담에 활용할 수 있는 피해 상황
요약 리포트를 작성해줘. 사용자의 피해 단계는 "{stage}"야.

【 작성 원칙 】
- 객관적 사실 위주로 정리 (누가, 언제, 어떻게, 무엇을 요구받았는지)
- 대화에서 확인되지 않은 정보는 추측해서 채우지 말고 "미확인"으로 표시
- 신고 접수 담당자가 빠르게 상황을 파악할 수 있도록 간결하게

【 응답 형식 - JSON만, 다른 텍스트 금지 】
{{
  "incident_summary": "사건 개요 한 문단",
  "timeline": ["시간 순서대로 정리된 사실 1", "사실 2", "..."],
  "requested_by_scammer": ["상대방이 요구했던 것들"],
  "amount_lost": "피해 금액 (확인 안 되면 '미확인')"
}}
"""

EVIDENCE_CHECKLIST_SYSTEM = """
너는 청년층 금융사기 대응을 돕는 AI 상담사 "든든이"야.
사용자의 피해 단계는 "{stage}"야. 이 상황에서 나중에 신고나 수사에 필요할 수
있는 증거를 놓치지 않도록, 지금 바로 확인/보존해야 할 체크리스트를 만들어줘.

【 작성 원칙 】
- 단계에 맞는 증거 위주로: 예) 금융피해 단계면 계좌이체 내역, 문자/카톡 캡처,
  통화 녹음 여부 등
- 사용자가 체크박스처럼 하나씩 확인할 수 있는 짧은 항목들로 구성
- 이미 삭제됐을 수 있는 것(문자, 앱)은 "삭제했어도 통신사에 기록 요청 가능"처럼
  포기하지 않아도 된다는 점을 언급

【 응답 형식 - JSON만, 다른 텍스트 금지 】
{{
  "checklist": ["확인할 항목 1", "확인할 항목 2", "..."]
}}
"""


def generate_report_script(stage: str, chat_messages: list[dict], refund_eligible: bool | None = None) -> dict:
    """플로우차트: 금융기관/경찰 신고용 전화 대본 만들기"""
    fallback = {"title": "신고 전화 대본", "script_lines": []}
    if refund_eligible is True:
        refund_note = REFUND_ELIGIBLE_NOTE
    elif refund_eligible is False:
        refund_note = REFUND_INELIGIBLE_NOTE
    else:
        refund_note = ""
    system = REPORT_SCRIPT_SYSTEM.format(stage=stage, refund_note=refund_note)
    raw = call_llm(system, chat_messages, temperature=0.4)
    return parse_json_safe(raw, fallback)


def generate_damage_report(stage: str, chat_messages: list[dict]) -> dict:
    """플로우차트: 피해 상황 요약 리포트 만들기"""
    fallback = {
        "incident_summary": "미확인",
        "timeline": [],
        "requested_by_scammer": [],
        "amount_lost": "미확인",
    }
    raw = call_llm(DAMAGE_REPORT_SYSTEM.format(stage=stage), chat_messages, temperature=0.4)
    return parse_json_safe(raw, fallback)


def generate_evidence_checklist(stage: str, chat_messages: list[dict]) -> dict:
    """플로우차트: 증거 보존 체크리스트 제공"""
    fallback = {"checklist": []}
    raw = call_llm(EVIDENCE_CHECKLIST_SYSTEM.format(stage=stage), chat_messages, temperature=0.4)
    return parse_json_safe(raw, fallback)
