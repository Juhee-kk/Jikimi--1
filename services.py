"""LLM 호출 / 진단 로직 / 대응 가이드·도구 생성.

Upstage Solar Pro(solar-pro4)를 OpenAI 호환 chat completions 형식으로 호출한다.
전체 흐름은 docs/PIPELINE (1).md 명세를 따른다: suspicion → damage_stage → guided.
"""

from __future__ import annotations

import json
import os
import re

import requests

import mock_data as data

UPSTAGE_URL = "https://api.upstage.ai/v1/chat/completions"
MODEL = "solar-pro4"


class MissingUpstageAPIError(RuntimeError):
    """Raised when the Upstage API key is not available in the environment."""


def contains_sensitive_info(text: str) -> bool:
    """주민번호 패턴이나 비밀번호/인증번호 + 숫자 조합이 보이면 True."""
    if re.search(r"\d{6}-?\d{7}", text):
        return True
    if any(k in text for k in ("비밀번호", "인증번호", "otp", "OTP")) and re.search(r"\d{4,}", text):
        return True
    return False


def call_llm(system: str, messages: list[dict], temperature: float = 0.3) -> str:
    api_key = os.getenv("UPSTAGE_API")
    if not api_key:
        raise MissingUpstageAPIError("UPSTAGE_API 환경변수가 필요합니다.")

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
# 분류 함수 ① — 사기 의심 여부
# ---------------------------------------------------------------------------

SUSPICION_SYSTEM = """당신은 금융사기 위험 신호를 분석하는 보조 도구다.
사용자가 겪고 있는 상황 설명을 읽고 아래 JSON만 출력하라. 다른 텍스트 금지.

{"label": "의심" | "낮음" | "근거부족",
 "confidence": 0~100 정수,
 "signals": ["감지된 위험 신호를 짧은 한국어 구로"],
 "follow_up": "근거부족일 때 사용자에게 물어볼 질문 1개 (다른 label이면 빈 문자열)"}

판정 기준:
- "의심": 다음 신호가 하나라도 명확하면. 선입금·보증금 요구 / 개인정보·신분증·계좌 요구 /
  수사기관·금융기관 사칭 정황 / 비밀 유지 강요 / 외부 메신저(텔레그램 등) 이동 유도 /
  출금 거부·추가 입금 요구 / 검증 불가한 고수익 약속 / 앱 설치 유도
- "낮음": 상황이 충분히 설명됐고 위 신호가 없으면
- "근거부족": 정보가 부족해 판단할 수 없으면. follow_up에는 판단에 가장 결정적인
  것 하나만 질문 (예: "혹시 상대방이 돈이나 개인정보를 요구한 적 있나요?")

절대 규칙: "사기가 확실하다"는 단정 금지. signals는 관찰된 사실만 기술."""


def classify_suspicion(chat_messages: list[dict]) -> dict:
    fallback = {
        "label": "근거부족",
        "confidence": 0,
        "signals": [],
        "follow_up": "상황을 조금 더 자세히 알려주실 수 있나요? 상대방이 뭐라고 했는지, 어떤 요구를 받았는지 궁금해요.",
    }
    raw = call_llm(SUSPICION_SYSTEM, chat_messages)
    result = parse_json_safe(raw, fallback)
    if result.get("label") not in ("의심", "낮음", "근거부족"):
        return fallback
    return result


# ---------------------------------------------------------------------------
# 분류 함수 ② — 피해 단계
# ---------------------------------------------------------------------------

STAGE_SYSTEM = """당신은 금융사기 피해 진행 단계를 분류하는 보조 도구다.
대화를 읽고 아래 JSON만 출력하라. 다른 텍스트 금지.

{"stage": "접촉초기" | "개인정보제공" | "링크클릭앱설치" | "입금송금" | "근거부족",
 "follow_up": "근거부족일 때 물어볼 질문 1개 (아니면 빈 문자열)"}

단계 정의 (해당되는 가장 진행된 단계 하나를 고른다):
- "입금송금": 이미 돈을 보냈거나 이체·환전을 완료함 → 가장 우선 판정
- "링크클릭앱설치": 링크를 눌렀거나 앱·프로그램을 설치함 (돈은 아직 안 보냄)
- "개인정보제공": 신분증·계좌번호·비밀번호 등 개인정보를 넘김 (링크/입금은 아직)
- "접촉초기": 연락만 받았고 아직 아무것도 제공하지 않음
- "근거부족": 위를 판단할 정보가 없음. follow_up 예:
  "혹시 지금까지 돈을 보내거나, 링크를 누르거나, 개인정보를 알려준 적이 있나요?"
"""


def classify_damage_stage(chat_messages: list[dict]) -> dict:
    fallback = {
        "stage": "근거부족",
        "follow_up": "혹시 지금까지 돈을 보내거나, 링크를 누르거나, 개인정보를 알려주신 적이 있나요?",
    }
    raw = call_llm(STAGE_SYSTEM, chat_messages)
    result = parse_json_safe(raw, fallback)
    if result.get("stage") not in ("접촉초기", "개인정보제공", "링크클릭앱설치", "입금송금", "근거부족"):
        return fallback
    return result


# ---------------------------------------------------------------------------
# 대응 가이드 — 고정 템플릿(mock_data.GUIDE_TEMPLATES) + LLM 공감 인트로
# ---------------------------------------------------------------------------

GUIDE_INTRO_SYSTEM = """사용자의 상황에 공감하는 문장 1~2개를 한국어로 써라.
- 사용자를 탓하지 말 것. "당황스러우셨겠어요" 같은 톤
- 사기 확정 단정 금지. "위험 신호가 보여요" 수준까지만
- 이어서 구체적 행동 안내가 나올 것이므로, 행동 지시는 쓰지 말 것
- 2문장 이내, 순수 텍스트만"""


def make_guide(stage: str, chat_messages: list[dict]) -> str:
    intro = call_llm(GUIDE_INTRO_SYSTEM, chat_messages, temperature=0.7)
    return intro.strip() + "\n\n" + data.GUIDE_TEMPLATES[stage]


# ---------------------------------------------------------------------------
# 대응 도구 3종 — 버튼 클릭 시에만 생성
# ---------------------------------------------------------------------------

TOOL_SYSTEMS = {
    "call_script": """사용자가 은행/경찰에 신고 전화할 때 그대로 읽을 수 있는 대본을 써라.
형식: ① 첫마디 (본인 소개 + 용건 한 문장) ② 피해 내용 설명 (대화에서 파악된
사실만: 언제, 어떤 경로로, 무엇을 요구받았고, 무엇을 제공/송금했는지)
③ 요청 사항 (지급정지/피해구제 등 단계에 맞게) ④ 상담원이 물어볼 만한 질문과 답
대화에 없는 사실(금액, 날짜, 계좌번호)은 지어내지 말고 [직접 입력] 으로 표시하라.""",
    "report": """피해 상황 요약 리포트를 써라. 신고·상담 시 제출용.
형식: 사건 개요(3줄 이내) / 시간 순 경과 / 상대방 정보(알려진 것만) /
제공·송금한 것 / 감지된 위험 신호 목록
대화에 없는 정보는 [확인 필요]로 표시. 추측 금지.""",
    "checklist": """증거 보존 체크리스트를 써라. 체크박스(- [ ]) 형식.
항목: 대화 캡처(날짜 보이게), 상대 프로필/계정 캡처, 송금 내역 캡처,
통화 녹음 백업, 상대 계좌·전화번호 기록, 원본 삭제 금지 안내
사용자 상황(피해 단계)에 맞는 항목 위주로 6~10개.""",
}


def make_tool(tool: str, stage: str, chat_messages: list[dict]) -> str:
    context = chat_messages + [
        {"role": "user", "content": f"(시스템 참고: 판정된 피해 단계는 '{stage}')"}
    ]
    return call_llm(TOOL_SYSTEMS[tool], context, temperature=0.4)
