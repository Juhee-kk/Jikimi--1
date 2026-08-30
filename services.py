"""LLM 호출 / 진단 로직 / 대응 가이드·도구 생성.

Upstage Solar Pro(solar-pro4)를 OpenAI 호환 chat completions 형식으로 호출한다.

흐름:
  0) 사용자 상황을 한 줄로 구조화 (extract_user_modus_operandi, LLM)
       → user_modus_operandi. DB의 modus_operandi_ko 필드와 같은 결의 요약문.
  1) 사기 의심 판정 = 유사도 DB 검색 (search_similar_cases, **미구현 스텁**)
       - user_modus_operandi를 질의문으로 사용
       - 유사도 >= SIMILARITY_THRESHOLD → 바로 2)
       - 미만 → 가장 유사한 사례를 보여주고 사용자 확인(예/아니오)
                예 → 2) / 아니오 → make_self_check(user_modus_operandi) 안내로 종료
  2) 피해 단계 분류 (classify_damage_stage, LLM)
  3) 대응 가이드 (make_guide = LLM 공감 인트로 + guide_templates 고정 템플릿)
"""

from __future__ import annotations

import json
import os
import re

import requests

import guide_templates

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
# 사기 의심 판정 ① — [미구현] 유사도 기반 DB 검색으로 대체 예정
# ---------------------------------------------------------------------------
#
# 예전엔 LLM이 "의심/낮음/근거부족"을 판정했다(classify_suspicion). 이제는
# 사용자 상황을 과거 사기 사례 DB와 유사도로 비교해서:
#   - 유사도 >= SIMILARITY_THRESHOLD  → '사기 확실' → 바로 피해단계 진단으로
#   - 유사도 <  SIMILARITY_THRESHOLD  → '불확실'   → 가장 유사한 사례를 사용자에게
#                                       보여주고 스스로 판단(예/아니오)하게 한다
#
# 아래 search_similar_cases() 는 아직 껍데기다. 유사도 검색을 실제로 붙일 자리.

SIMILARITY_THRESHOLD = 0.75  # 이 값 이상이면 '사기 확실'

EXTRACT_MODUS_OPERANDI_SYSTEM = """대화를 읽고, 사용자가 겪은 상황을 한 문장으로 요약하라.
- 과거 사기 사례 DB의 'modus_operandi_ko' 필드와 같은 결: "누가/무엇을 사칭해 어떤 방식으로
  접근했고, 무엇을 요구했는지"를 담은 한 문장.
- 대화에 있는 사실만 담아라. 없는 내용은 지어내지 마라.
- 사기라고 단정하는 표현은 쓰지 마라 (예: "~사기" 대신 "~을 요구받음" 식으로 서술).
- 한 문장, 순수 텍스트만 출력. 다른 설명·따옴표 금지."""


def extract_user_modus_operandi(chat_messages: list[dict]) -> str:
    """대화를 '사용자 상황 한 줄 요약'으로 구조화한다 (DB의 modus_operandi_ko와 같은 결).

    이렇게 만든 user_modus_operandi는 두 군데서 쓰인다:
      - search_similar_cases()의 검색 질의문
      - make_self_check()가 확인 전화 대본을 만드는 근거
    """
    return call_llm(EXTRACT_MODUS_OPERANDI_SYSTEM, chat_messages, temperature=0.2).strip()


def search_similar_cases(user_modus_operandi: str) -> dict:
    """user_modus_operandi(사용자 상황 한 줄 요약)와 가장 비슷한 과거 사기 사례를
    유사도로 찾는다. **[미구현]**

    실제 구현 시 data/structured_scam_articles.jsonl 등을 임베딩/유사도 검색해
    아래 형태를 채워 반환하면 된다. 지금은 로직 배선을 위한 더미값만 돌려준다.

    반환:
      {
        "similarity": float,            # 0.0~1.0, 가장 유사한 사례와의 점수
        "case": {                       # 사용자에게 보여줄 가장 유사한 사례 (없으면 None)
            "headline_ko": str,
            "summary_ko": str,
            "modus_operandi_ko": str,
            "warning_signs": list[str],
        } | None,
      }
    """
    # TODO: 유사도 검색 구현. 아래는 임시 더미 — 항상 '불확실' 경로로 빠진다.
    similarity = 0.0
    case = {
        "headline_ko": "(유사 사례 검색 미구현)",
        "summary_ko": "여기에 유사도로 찾은 가장 비슷한 사기 사례 요약이 들어갑니다.",
        "modus_operandi_ko": "",
        "warning_signs": [],
    }
    return {"similarity": similarity, "case": case}


def is_fraud_certain(similarity: float) -> bool:
    """유사도가 임계값 이상이면 '사기 확실'."""
    return similarity >= SIMILARITY_THRESHOLD


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
# 대응 가이드 — 고정 템플릿(guide_templates.GUIDE_TEMPLATES) + LLM 공감 인트로
# ---------------------------------------------------------------------------

GUIDE_INTRO_SYSTEM = """사용자의 상황에 공감하는 문장 1~2개를 한국어로 써라.
- 사용자를 탓하지 말 것. "당황스러우셨겠어요" 같은 톤
- 사기 확정 단정 금지. "위험 신호가 보여요" 수준까지만
- 이어서 구체적 행동 안내가 나올 것이므로, 행동 지시는 쓰지 말 것
- 2문장 이내, 순수 텍스트만"""


def make_guide(stage: str, chat_messages: list[dict]) -> str:
    intro = call_llm(GUIDE_INTRO_SYSTEM, chat_messages, temperature=0.7)
    return intro.strip() + "\n\n" + guide_templates.resolve(stage)


SELF_CHECK_SCRIPT_SYSTEM = """사용자가 상대의 신원을 확인하려고 관련 기관·회사에 직접
전화할 때 그대로 읽을 수 있는 확인 멘트를 써라. 아직 사기라고 단정된 상황이 아니라
'사실 확인'을 위한 전화임을 잊지 말 것.

형식(자연스러운 대화체 문단 2~4문장, 마크다운 불릿 금지):
① 첫마디: 본인 소개 + 확인차 전화했다는 용건
② 상황 설명: 아래 '사용자 상황' 요약을 그대로 반영 (없는 사실 추가·과장 금지)
③ 확인 질문: "실제로 이런 연락을 보내셨거나 이런 절차가 있는 게 맞는지" 형태로 마무리"""


def make_self_check(user_modus_operandi: str) -> str:
    """사기 의심이 '불확실'이고 사용자가 유사 사례와 다르다고 답했을 때 주는 안내.

    사기 확정이 아니므로 공감 인트로는 없다. 대신 guide_templates.SELF_CHECK_GUIDE의
    {generated_script} 자리에, user_modus_operandi(extract_user_modus_operandi로
    구조화된 사용자 상황 한 줄 요약)를 근거로 LLM이 만든 확인 전화 대본을 채워 넣는다.
    """
    script = call_llm(
        SELF_CHECK_SCRIPT_SYSTEM,
        [{"role": "user", "content": f"사용자 상황: {user_modus_operandi}"}],
        temperature=0.4,
    )
    return guide_templates.SELF_CHECK_GUIDE.format(generated_script=script.strip())


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
