"""진단 로직 / 전화 대본 / 사건 요약 리포트.

지금은 mock_data.FRAUD_TYPES의 키워드를 기준으로 한 규칙 기반 mock 진단만 동작합니다.
실제 LLM(Claude/OpenAI 등) provider가 정해지면 call_llm()만 구현하고
USE_LLM 플래그를 켜면 됩니다 — diagnose()의 나머지 흐름은 그대로 재사용됩니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import mock_data as data

USE_LLM = False


@dataclass
class DiagnosisResult:
    level: str  # "safe" | "caution" | "danger" | "damage"
    fraud_type_id: str | None
    headline: str
    body: str
    evidence: list[dict] = field(default_factory=list)
    followup_question: str | None = None


def contains_sensitive_info(text: str) -> bool:
    """주민번호 패턴이나 비밀번호/인증번호 + 숫자 조합이 보이면 True."""
    if re.search(r"\d{6}-?\d{7}", text):
        return True
    if any(k in text for k in ("비밀번호", "인증번호", "otp", "OTP")) and re.search(r"\d{4,}", text):
        return True
    return False


def call_llm(prompt: str) -> str:
    """TODO: LLM provider 결정되면 여기에 실제 API 호출을 구현."""
    raise NotImplementedError("LLM provider가 아직 정해지지 않았어요 — mock 진단으로 대체됩니다.")


def _match_fraud_type(combined_text: str):
    best_type, best_score, matched_keywords = None, 0, []
    for fraud_type in data.FRAUD_TYPES:
        hits = [kw for kw in fraud_type["keywords"] if kw in combined_text]
        if len(hits) > best_score:
            best_type, best_score, matched_keywords = fraud_type, len(hits), hits
    return best_type, best_score, matched_keywords


def _followup_for(fraud_type_id: str | None, level: str) -> str | None:
    if level in ("safe", "damage"):
        return None
    mapping = {
        "romance_scam": "relationship_duration",
        "smishing": "link_click",
        "voice_phishing": "app_install",
        "loan_scam": "app_install",
        "secondhand_scam": "counterpart_info",
    }
    key = mapping.get(fraud_type_id, "remittance")
    return data.FOLLOWUP_PROMPTS[key]


def _mock_diagnose(user_text: str, history: list[dict]) -> DiagnosisResult:
    combined = user_text + " " + " ".join(m.get("content", "") for m in history if m.get("role") == "user")

    if any(kw in combined for kw in data.DAMAGE_KEYWORDS):
        level = "damage"
        fraud_type, _, matched_keywords = _match_fraud_type(combined)
    else:
        fraud_type, score, matched_keywords = _match_fraud_type(combined)
        if score >= 2:
            level = "danger"
        elif score == 1:
            level = "caution"
        else:
            level = "safe"

    info = data.RISK_LEVELS[level]
    headline = info["headline"]
    body = info["body"]
    if fraud_type:
        body += f'\n\n**{fraud_type["icon"]} {fraud_type["title"]}** 유형과 겹치는 부분이 있어요.'

    evidence = []
    for kw in matched_keywords[:2]:
        evidence.append(
            {
                "quote": kw,
                "explain": f'{fraud_type["title"] if fraud_type else "의심 사기"}에서 자주 나오는 표현이에요',
                "source": "텅장지키미 패턴 데이터베이스 (mock)",
            }
        )

    return DiagnosisResult(
        level=level,
        fraud_type_id=fraud_type["id"] if fraud_type else None,
        headline=headline,
        body=body,
        evidence=evidence,
        followup_question=_followup_for(fraud_type["id"] if fraud_type else None, level),
    )


def diagnose(user_text: str, history: list[dict] | None = None) -> DiagnosisResult:
    history = history or []
    if USE_LLM:
        try:
            call_llm(user_text)
        except NotImplementedError:
            pass
    return _mock_diagnose(user_text, history)


def generate_phone_script(fraud_type_id: str | None) -> dict:
    fraud_type = data.FRAUD_TYPE_BY_ID.get(fraud_type_id)
    type_title = fraud_type["title"] if fraud_type else "의심되는 상황"
    return {
        "intro": data.PHONE_SCRIPT_INTRO,
        "opening": f"안녕하세요, {type_title}으로 의심되는 상황이 있어서 지급정지 요청드리려고 전화드렸습니다.",
        "expected_qna": [
            ("성함과 계좌번호를 알려주시겠어요?", "본인 이름과 계좌번호를 준비해두고 그대로 답하면 돼요."),
            ("언제, 얼마를 이체하셨나요?", "이체 시각과 금액을 미리 캡처나 메모로 확인해두세요."),
            ("상대방 계좌 정보를 알고 계신가요?", "문자·대화에 남아있는 상대 계좌번호나 전화번호를 불러주세요."),
        ],
        "must_say": ["지급정지 요청합니다", "피해구제 신청도 함께 접수하고 싶어요"],
        "after_call": ["접수번호", "담당자명", "통화한 시각"],
    }


def generate_case_report(chat_history: list[dict]) -> str:
    lines = ["# 텅장지키미 상담 요약", "", "## 대화 내용", ""]
    for msg in chat_history:
        speaker = "사용자" if msg.get("role") == "user" else "텅장지키미"
        lines.append(f"- **{speaker}**: {msg.get('content', '')}")
    lines.append("")
    lines.append("---")
    lines.append(data.DISCLAIMER_TEXT)
    return "\n".join(lines)
