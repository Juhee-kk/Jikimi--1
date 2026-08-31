"""상황 진단 챗봇의 로직. 화면은 pages_files/chat.py에 있다.

목표 플로우와 이 파일의 함수가 대응하는 방식:

  ① 사용자 상황 입력                     (chat.py가 받는다)
  ② 답변 구조화                          structure_situation()
       필수 필드가 비면 되묻고 다시 ②로    missing_required_fields() / ask_for()
       되묻기는 MAX_FOLLOW_UP_ROUNDS번까지. 그 이상은 모자란 채로 ③에 넘긴다.
  ③ 구조화 정보로 DB 사례 검색            search_similar_cases()
       1단계 recall  Qdrant 임베딩 검색으로 넓게 건진다      recall_cases()
                     같은 사건의 중복 기사를 접는다          dedupe_cases()
       2단계 판정    LLM이 포섭 관계를 보고 Coverage를 낸다   judge_coverage()
       Coverage로 세 갈래                                 decide()
         confirmed    (≥0.8)      → ④
         needs_confirm(0.6~0.8)   → 후보를 보여주고 사용자 확인
                                     예 → ④ / 아니오 → 4-B
         insufficient (<0.6)      → 4-B
  ④ 피해 단계 진단                        classify_damage_stage()
       접촉초기 / 개인정보제공 / 링크클릭앱설치 / 입금송금
  ⑤ 단계별 대응 가이드와 도구 3종          make_guide() / make_tool()
       신고 전화 대본 · 피해 요약 리포트 · 증거 보존 체크리스트

  4-B 사기라 단정할 수 없을 때             make_agency_inquiry_script()
       어디에 확인할지 안내하고, 전화 대본은 버튼을 눌렀을 때 따로 낸다.
       못 찾은 것을 사기로 몰지 않고, 사용자가 스스로 확인하게 하는 출구다.

--- 설계에서 판단이 갈렸던 지점들 ---

검색이 '유사도'가 아니라 '포섭'인 이유
  DB에는 일반화된 수법이, 사용자에게는 구체적 사건이 있다. 물어야 할 것은
  "이 둘이 얼마나 비슷한가"(대칭)가 아니라 "사용자 상황이 이 수법의 한 사례로
  설명되는가"(비대칭)다.

왜 2단계인가
  266건을 전부 LLM에 넣을 수는 없고, 임베딩만으로는 포섭 관계도 판정 근거도 낼 수 없다.
  임베딩은 거르는 역할, LLM은 판단하는 역할로 나눈다.

왜 축을 세워 비교하나 (AXES)
  덩어리 텍스트끼리 던지면 LLM이 매번 비교 기준을 스스로 정하고, 결과의 일치 근거가
  자유서술로 나와 화면에 쓸 수도 집계할 수도 없다. 사용자·사례 스키마가 원래 1:1로
  대응하므로 다섯 축 위에 나란히 세운다. 덕분에 "접근경로·사칭대상·유인이 일치한다"는
  근거를 사용자에게 그대로 보여줄 수 있다.

왜 점수가 아니라 범주를 받나 (CATEGORY_SCORES)
  LLM에게 0~1 점수를 물으면 프롬프트에 적힌 앵커값만 뱉는데, 그 값이 하필 분기
  임계값과 같아 경계에서 판정이 진동한다. 범주로 받아 코드에서 점수로 옮긴다.
  분기는 범주가 천장을, 점수가 바닥을 정한다 — partial은 점수가 아무리 높아도
  확정으로 올리지 않고 사용자 확인을 거친다.

모델을 나눠 쓰는 이유
  구조화는 정형 추출이라 solar-mini로 충분하고 빠르다. 포섭 판정과 문안 작성은
  solar-pro4를 쓴다.

알려진 한계
  2단계 판정이 후보 구성에 따라 흔들린다. 1단계가 1위로 지목한 사례가 판정에서
  2위로 밀리는 경우가 관측됐다(골든셋 #15). 임베딩 순위는 현재 동점일 때의
  보조 정렬 기준으로만 쓰이고 Coverage 계산에는 반영되지 않는다.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

import guide_templates
import scam_data_pipeline as pipeline

# 키·설정을 읽는 창구를 파이프라인과 하나로 맞춘다. Streamlit Cloud 는 secrets 로,
# 로컬과 CI 는 환경변수로 키를 준다. 그 차이는 pipeline.get_secret 이 흡수한다.
get_secret = pipeline.get_secret

UPSTAGE_CHAT_URL = "https://api.upstage.ai/v1/chat/completions"
UPSTAGE_EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"
MODEL = "solar-pro4"
STRUCTURING_MODEL = get_secret("UPSTAGE_STRUCTURING_MODEL", "solar-mini")
EMBEDDING_QUERY_MODEL = get_secret("UPSTAGE_EMBEDDING_QUERY_MODEL", "embedding-query")


class MissingUpstageAPIError(RuntimeError):
    """Upstage API 키가 환경에 없을 때."""


# ---------------------------------------------------------------------------
# 공용
# ---------------------------------------------------------------------------


def contains_sensitive_info(text: str) -> bool:
    """주민번호 패턴이나 비밀번호/인증번호 + 숫자 조합이 보이면 True."""
    if re.search(r"\d{6}-?\d{7}", text):
        return True
    if any(k in text for k in ("비밀번호", "인증번호", "otp", "OTP")) and re.search(r"\d{4,}", text):
        return True
    return False


def _api_key() -> str:
    key = get_secret("UPSTAGE_API") or get_secret("UPSTAGE_API_KEY")
    if not key:
        raise MissingUpstageAPIError(
            "UPSTAGE_API 키가 없습니다. 배포본은 Streamlit Secrets, 로컬은 환경변수로 넣어 주세요."
        )
    return key


# 429는 잠시 뒤 다시 걸면 대개 통과한다. 재시도가 없으면 사용자 화면에 바로 오류가 뜬다.
_RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}


def _post(url: str, payload: dict, timeout: int = 40, retries: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(1, retries + 1):
        response = requests.post(
            url,
            headers={"Authorization": f"Bearer {_api_key()}"},
            json=payload,
            timeout=timeout,
        )
        if response.status_code not in _RETRY_STATUS:
            response.raise_for_status()
            return response.json()
        last = requests.HTTPError(f"HTTP {response.status_code}", response=response)
        if attempt < retries:
            wait = float(response.headers.get("Retry-After") or 2 ** attempt)
            time.sleep(min(wait, 20))
    raise last  # type: ignore[misc]


def call_llm(system: str, messages: list[dict], temperature: float = 0.3, model: str = MODEL) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "temperature": temperature,
    }
    return _post(UPSTAGE_CHAT_URL, payload)["choices"][0]["message"]["content"]


def parse_json_safe(text: str, fallback: Any) -> Any:
    """```json 펜스와 앞뒤 잡설을 걷어내고 JSON을 꺼낸다. 실패하면 fallback."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"[\[{].*[\]}]", stripped, flags=re.DOTALL)
        if not match:
            return fallback
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return fallback


as_text = pipeline.as_text
as_list = pipeline.as_list


# ---------------------------------------------------------------------------
# ① 사용자 상황 구조화
#
# 사례 DB와 같은 축으로 뽑아야 뒤에서 나란히 비교할 수 있다.
# (DB 필드, 한글 라벨, 사용자 필드) — 이 다섯이 Coverage의 어휘다.
# ---------------------------------------------------------------------------

AXES = [
    ("approach_channel", "접근경로", "contact_channel"),
    ("impersonation_target", "사칭대상", "stated_identity"),
    ("lure_hook", "유인", "key_context"),
    ("victim_action_requested", "요구행동", "requested_action"),
    ("payment_method", "결제·송금수단", "money_method"),
]
AXIS_IDS = [db for db, _, _ in AXES]

# 이게 없으면 검색이 성립하지 않는 필드. 비면 되묻는다.
#
# 기준은 하나다 — query_text() 가 실제로 쓰는 값인가. 검색 질의문은
# user_modus_operandi(+situation_summary) · key_context · requested_action 으로 만든다.
# 앞의 하나는 LLM 이 발화에서 늘 만들어 내므로, 되물어서 얻어야 하는 건 이 둘뿐이다.
#
# 접근경로(contact_channel)와 사칭대상(stated_identity)은 여기 없다. AXES 의 축이긴
# 하지만 query_text 에도 사례 쪽 RETRIEVAL_FIELDS 에도 들어가지 않아 1단계 recall 에
# 쓰이지 않고, coverage_score 의 분모는 '사용자가 실제로 말한 축'이라 비어 있어도
# 감점이 없다. 검색을 막지 않는 값 때문에 사기 판정을 한 턴 늦출 이유가 없다.
#
# 사칭대상은 특히 '없는 게 정상'인 수법이 있어서 필수로 두면 안 된다. 착오송금 후
# 재송금 요구, 개인 판매자 사칭처럼 상대가 아무 신분도 대지 않는 유형에서는 물어봐야
# 돌아올 답이 "모르는 사람"뿐이다. 검색을 한 턴 늦추고 사용자에게는 방금 한 말을
# 못 알아들은 것처럼 보인다. 이런 값은 사기로 판정된 뒤 DIAGNOSIS_FIELDS 에서 챙긴다.
REQUIRED_FIELDS = ["key_context", "requested_action"]

# 필드별 되묻기 문구. LLM으로 생성하면 톤이 흔들려서 고정 문구를 쓴다.
FIELD_QUESTIONS = {
    "contact_channel": "그 연락은 어떤 경로로 왔나요? (전화, 문자, 카카오톡, SNS, 이메일 등)",
    "stated_identity": "상대가 자기를 누구라고 하던가요? (기관·회사 이름이나 직책. 안 밝혔으면 그렇게 알려주세요)",
    "key_context": "무슨 이유로 연락이 왔다고 하던가요?",
    "requested_action": "상대가 뭘 하라고 하던가요? (링크 클릭, 앱 설치, 송금, 개인정보 입력 등)",
    "taken_action": "그중에 이미 하신 게 있나요? 아직 아무것도 안 하셨다면 그렇게 말씀해 주세요.",
    "money_method": "돈을 요구했다면 어떤 방식으로 보내라고 하던가요?",
}

# 사기로 판정된 뒤 빈칸을 훑는 단계. 검색 관문을 두 개로 좁힌 만큼, 여기서는 남은
# 필드 전부를 대상으로 본다. 피해 단계 진단과 산출물(신고 대본·리포트)이 쓰는 값이
# 여기서 채워진다. 4-B 로 빠질 사용자에게는 이 단계 자체가 없다 — 쓸 데가 없는
# 질문이 되기 때문이다.
#
# 순서가 곧 질문 순서다(MAX_FIELDS_PER_QUESTION 만큼 앞에서 자른다). 피해 단계를
# 가르는 taken_action 이 맨 앞이고, 검색 관문을 이미 통과한 key_context·requested_action
# 은 사실상 차 있어 맨 뒤에 둔다.
DIAGNOSIS_FIELDS = [
    "taken_action", "contact_channel", "stated_identity", "money_method",
    "key_context", "requested_action",
]

# 이 단계에서는 unknown_fields 게이트를 쓰지 않는다. 여섯 필드 모두 대응 안내의
# 정확도를 실제로 좌우하는 값이라, 비어 있으면 한 번은 물어볼 값어치가 있다.
# 대신 같은 필드를 두 번 묻지 않는다 — 그 역할은 호출부가 넘기는 asked 가 한다.
# 게이트를 그대로 뒀다면 "돈 요구는 없었어요"라고 답한 사용자에게 money_method 를
# 다시 묻게 되는데, 그 반복을 막는 건 게이트가 아니라 '이미 물어봤다'는 기억이다.

MAX_FOLLOW_UP_ROUNDS = 2      # 이 이상 되묻지 않는다. 사용자를 지치게 하면 안 된다.
MAX_DETAIL_ROUNDS = 2         # 판정 뒤 추가 질문도 같은 이유로 상한을 둔다.
MAX_FIELDS_PER_QUESTION = 2   # 한 번에 두 개까지만 묻는다.

STRUCTURING_SYSTEM = """당신은 사용자가 설명한 상황을 요약하기 위한 정보 추출기입니다.
사기 여부나 상대방의 진위를 판단하지 말고, 발화에 나온 사실만 구조화하세요.

{
  "user_modus_operandi": "",
  "situation_summary": "",
  "contact_channel": [],
  "stated_identity": [],
  "key_context": [],
  "requested_action": [],
  "taken_action": [],
  "money_method": [],
  "unknown_fields": []
}

필드 설명:
- user_modus_operandi: "누가/무엇을 사칭해 어떤 방식으로 접근했고, 무엇을 요구했는지"를 담은
  한 문장. 사기라고 단정하지 말고 "~을 요구받음" 식으로 서술한다.
- situation_summary: 상황의 흐름을 한국어 한 문장으로.
- contact_channel: 연락·접촉 경로. 예: 전화, 문자, 카카오톡, SNS, 이메일, 웹사이트.
  발화에 경로가 **명시되지 않았으면 절대 추측해 채우지 말고** []로 두고
  unknown_fields에 "contact_channel"을 넣는다. "연락이 왔다", "물어봤다"만으로는
  전화인지 문자인지 알 수 없다. 이런 경우가 추측의 대표적인 함정이다.
  반대로 "전화가 와서", "문자를 받았는데", "카톡으로" 처럼 수단이 말에 드러나 있으면
  그대로 채운다. 추측 금지는 없는 것을 지어내지 말라는 뜻이지, 나온 것을 버리라는
  뜻이 아니다.
- stated_identity: 상대가 밝힌 이름·기관·소속.
  상대가 신분을 대지 않았다는 사실이 발화에 드러나면("모르는 사람", "낯선 번호",
  "누군지 안 밝혔다") 값이 없는 것이 정상이다. []로 두고 unknown_fields에 넣지 마라.
  발화만으로는 밝혔는지조차 알 수 없을 때만 unknown_fields에 넣는다.
- key_context: 연락이나 행동의 이유·명목.
- requested_action: 상대가 요청하거나 유도한 행동.
- taken_action: 사용자가 **이미 실행한** 행동만. requested_action과 반드시 구분한다.
  요청받았으나 아직 하지 않은 것은 넣지 않는다. 아무것도 안 했으면 [].
- money_method: 요구받았거나 실제로 쓴 금전·결제 방식.
- unknown_fields: 발화만으로는 확인할 수 없어 **되물어야 하는** 필드명.
  상대가 실제로 아무것도 요구하지 않은 경우와, 요구 여부를 알 수 없는 경우를 구분한다.
  전자는 빈 배열로 두고 여기 넣지 않는다. 후자만 여기 넣는다.

출력 규칙:
- 유효한 JSON 객체만 출력한다.
- 없는 정보는 문자열 필드는 "", 배열 필드는 []로 둔다.
- 배열 필드는 값이 하나여도 반드시 배열로 출력한다.
- 발화에 없는 사실을 추측하거나 사기 여부를 판단하지 않는다."""

_STRUCT_KEYS = (
    "user_modus_operandi", "situation_summary", "contact_channel", "stated_identity",
    "key_context", "requested_action", "taken_action", "money_method", "unknown_fields",
)


def transcript_of(chat_messages: list[dict]) -> str:
    """대화를 한 덩어리 기록으로 만든다.

    모델에 대화를 messages 로 그대로 넘기면 자기 차례로 알아듣고 대화를 이어 쓴다.
    사실을 뽑거나 문서를 만들 때는 대화가 아니라 자료여야 한다.
    """
    return "\n".join(
        f"{'사용자' if m.get('role') == 'user' else '상담봇'}: {m.get('content', '')}"
        for m in chat_messages
    )


def structure_situation(chat_messages: list[dict]) -> dict:
    """대화를 읽어 구조화한다. 되물은 답까지 반영되도록 매번 전체를 다시 읽는다.

    넘길 대화는 호출부가 골라야 한다. 인사말이나 되묻기 질문 같은 짧은 어시스턴트
    발화는 추출을 돕는다 — 빼 보면 key_context 가 통째로 비는 등 결과가 얇아진다.
    반대로 위험 신호 목록이나 가이드처럼 긴 생성물이 끼면 모델이 추출을 그만두고
    빈 객체를 돌려준다. chat.py 의 _structuring_history() 가 그 경계를 담당한다.
    """
    raw = call_llm(STRUCTURING_SYSTEM, chat_messages, temperature=0, model=STRUCTURING_MODEL)
    data = parse_json_safe(raw, {})
    if not isinstance(data, dict):
        data = {}
    out: dict[str, Any] = {}
    for key in _STRUCT_KEYS:
        value = data.get(key)
        out[key] = as_text(value) if key in ("user_modus_operandi", "situation_summary") else as_list(value)
    return out


def missing_required_fields(structured: dict) -> list[str]:
    """되물어야 하는 필수 필드. '실제로 없음'과 '알 수 없음'을 구분한다.

    unknown_fields에 있으면 모르는 것이므로 묻고, 그냥 비어 있으면 해당 사실이 없는
    것으로 보고 넘어간다. 이 구분이 없으면 "상대가 아무것도 요구 안 했다"는 사용자에게
    계속 같은 질문을 하게 된다.

    """
    unknown = set(structured.get("unknown_fields") or [])
    return [f for f in REQUIRED_FIELDS if not structured.get(f) and f in unknown]


ASK_HEAD_SEARCH = "조금만 더 알려주시면 비슷한 사례를 찾아볼 수 있어요."
# 진단 단계는 '없을 수도 있는' 값까지 묻는다. 해당 없으면 그렇게 답해도 된다는 것을
# 머리말에서 먼저 알려야, 답할 게 없는 질문 앞에서 사용자가 막히지 않는다.
ASK_HEAD_DETAIL = (
    "이것만 알려주시면 더 정확하게 안내해드릴 수 있어요.\n해당 없는 건 \"없어요\"라고만 답해 주셔도 돼요."
)


def ask_for(fields: list[str], head: str = ASK_HEAD_SEARCH) -> str:
    picked = fields[:MAX_FIELDS_PER_QUESTION]
    lines = [FIELD_QUESTIONS[f] for f in picked if f in FIELD_QUESTIONS]
    return head + "\n\n" + "\n".join(f"- {line}" for line in lines)


def missing_diagnosis_fields(structured: dict, asked: set[str] | None = None) -> list[str]:
    """사기로 판단된 뒤 남은 빈칸을 훑는다. 검색 관문과 달리 unknown 게이트를 두지 않는다.

    여섯 필드 전부가 피해 단계 진단과 산출물의 정확도를 가르는 값이라, 비어 있으면
    한 번은 묻는다. 사용자가 "그런 건 없었어요"라고 답하면 필드는 여전히 비지만
    asked 에 남아 다시 묻지 않는다. 같은 질문의 반복을 막는 건 게이트가 아니라
    이 기억이다.
    """
    asked = asked or set()
    return [f for f in DIAGNOSIS_FIELDS if not structured.get(f) and f not in asked]


# ---------------------------------------------------------------------------
# ② 사례 검색 — 1단계 임베딩 recall, 2단계 LLM Coverage 판정
# ---------------------------------------------------------------------------

RECALL_TOP_N = 30    # 넓게 건진다. 여기 없으면 2단계가 살릴 수 없다.
JUDGE_TOP_N = 8      # 중복 제거 후 실제로 LLM에 넘길 수
FINAL_TOP_K = 3

COVERAGE_CERTAIN = 0.8      # 이상이면 사례 확정
COVERAGE_UNCERTAIN = 0.6    # 이상이면 사용자에게 확인, 미만이면 판단 근거 부족

# 점수를 직접 묻지 않고 범주로 받는다. 숫자를 물으면 프롬프트의 앵커값(0.8, 0.6)만
# 뱉는데 그게 하필 분기 임계값이라 경계에서 진동한다.
CATEGORY_SCORES = {"covered": 0.9, "partial": 0.7, "not_covered": 0.3}
AXIS_ADJUSTMENT = 0.15


def _embed_query(text: str) -> list[float]:
    payload = {"model": EMBEDDING_QUERY_MODEL, "input": [text]}
    return _post(UPSTAGE_EMBEDDING_URL, payload, timeout=30)["data"][0]["embedding"]


def query_text(structured: dict) -> str:
    """검색 질의문. 사례 쪽 RETRIEVAL_FIELDS(수법+유인+요구행동)와 결을 맞춘다."""
    parts = [
        structured.get("user_modus_operandi") or structured.get("situation_summary"),
        as_text(structured.get("key_context")),
        as_text(structured.get("requested_action")),
    ]
    return "\n".join(p for p in parts if p)


def _headline_tokens(text: str | None) -> set[str]:
    """토큰을 앞 2글자로 줄인 집합. 한국어 조사·어미 차이를 흡수한다."""
    cleaned = re.sub(r"\s*[-–—]\s*[^-–—]{1,25}$", "", (text or "").strip())
    return {t[:2] for t in re.split(r"[^\w가-힣]+", cleaned) if len(t) >= 2}


def dedupe_cases(cases: list[dict], limit: int) -> list[dict]:
    """같은 사건을 다룬 여러 매체 기사를 한 건으로 접는다.

    이걸 안 하면 상위 후보가 전부 같은 기사인 경우에 판정 호출을 통째로 낭비한다.
    """
    kept: list[dict] = []
    seen: list[set[str]] = []
    for case in cases:
        tokens = _headline_tokens(case.get("headline_ko"))
        if any(
            len(tokens & other) >= 3 and len(tokens & other) / (min(len(tokens), len(other)) or 1) >= 0.5
            for other in seen
        ):
            continue
        seen.append(tokens)
        kept.append(case)
        if len(kept) >= limit:
            break
    return kept


def recall_cases(structured: dict, limit: int = RECALL_TOP_N) -> list[dict]:
    """Qdrant에서 후보를 건진다. 색인은 넓게 두고 거르는 건 여기 query_filter로 한다."""
    from qdrant_client import QdrantClient
    from qdrant_client.models import FieldCondition, Filter, MatchAny

    api_key = get_secret("QDRANT_API_KEY")
    if not api_key:
        return []

    client = QdrantClient(url=pipeline.QDRANT_URL, api_key=api_key, timeout=20)
    hits = client.query_points(
        collection_name=pipeline.QDRANT_COLLECTION,
        query=_embed_query(query_text(structured)),
        limit=limit,
        with_payload=True,
        query_filter=Filter(
            must=[FieldCondition(key="article_type", match=MatchAny(any=["사례", "신종경보"]))]
        ),
    ).points

    cases = []
    for hit in hits:
        payload = dict(hit.payload or {})
        payload.update(payload.pop("display_metadata", {}))
        payload.update(payload.pop("filter_metadata", {}))
        payload["score"] = hit.score
        cases.append(payload)
    return cases


def axis_view(structured: dict, case: dict) -> str:
    """사용자와 사례를 같은 축 위에 나란히 세운다.

    덩어리 텍스트끼리 비교하면 LLM이 매번 비교 기준을 스스로 정하게 되고, 결과의
    일치 근거가 자유서술로 나와 화면에 쓸 수도 집계할 수도 없다.
    """
    lines = []
    for db_field, label, user_field in AXES:
        mine = as_text(structured.get(user_field)) or "—"
        theirs = as_text(case.get(db_field)) or "—"
        lines.append(f"  [{label}] ({db_field})\n      사용자: {mine}\n      DB    : {theirs}")
    return "\n".join(lines)


JUDGE_SYSTEM = "당신은 사기 수법의 포섭 관계를 평가하는 분류기입니다. 유효한 JSON만 출력합니다."


def build_judge_prompt(structured: dict, candidates: list[dict]) -> str:
    summary = as_text(structured.get("user_modus_operandi")) or as_text(structured.get("situation_summary"))
    blocks = [
        f"### 후보 {i}\n  DB 수법: {as_text(c.get('modus_operandi_ko')) or '(기술 없음)'}\n{axis_view(structured, c)}"
        for i, c in enumerate(candidates, start=1)
    ]
    return f"""사용자 상황이 각 후보 사례의 수법에 **포섭되는지** 평가하세요.

판정 원칙:
- 단어가 겹치는지가 아니라, 사용자 상황이 그 수법의 한 사례로 설명되는지를 봅니다.
- DB 사례가 더 일반적인 수법이고 사용자 상황이 그 구체적 사례라면 포섭됩니다.
- 진행 방식의 핵심(누가 사칭했고, 무엇으로 유인해, 무엇을 요구했는지)이 다르면 포섭이 아닙니다.
- 사기 여부를 새로 판단하지 마세요. 두 기술(記述) 사이의 포섭 관계만 봅니다.
- **어느 후보도 사용자 상황을 설명하지 못하면 전부 not_covered로 두세요.**
  억지로 하나를 고르지 마세요. 사용자가 정상적인 절차를 밟은 상황일 수도 있습니다.

각 후보에 대해:
- category: "covered"(핵심 수법이 같음) / "partial"(일부 구조만 같고 중요한 차이가 있음)
            / "not_covered"(다른 사례이거나 관련 없음)
- matched_axes: 실제로 일치하는 축의 id만. 반드시 이 중에서만 고르세요: {", ".join(AXIS_IDS)}
- key_difference: 가장 중요한 차이 한 가지. 없으면 "".

사용자 상황: {summary}
사용자가 이미 실행한 행동: {as_text(structured.get("taken_action")) or "없음/불명"}
  ↑ 참고 정보입니다. 축 비교 대상이 아니며 matched_axes에 넣지 마세요.

{chr(10).join(blocks)}

후보 {len(candidates)}개 전부에 대해 아래 JSON 배열만 출력하세요.
[{{"candidate": 1, "category": "partial", "matched_axes": [], "key_difference": ""}}]"""


def coverage_score(category: str, matched_axes: list[str], structured: dict) -> float:
    """범주 점수를 축 일치 비율로 미세 조정한다.

    분모는 '사용자가 실제로 말한 축'이다. 사용자가 세 축만 말했으면 그 셋으로 평가하고,
    DB 쪽이 비어 있다고 벌점을 주지 않는다.
    """
    base = CATEGORY_SCORES[category]
    stated = [db for db, _, uf in AXES if structured.get(uf)]
    if not stated:
        return base
    ratio = len([a for a in matched_axes if a in stated]) / len(stated)
    return round(min(1.0, max(0.0, base + AXIS_ADJUSTMENT * (ratio - 0.5) * 2)), 3)


def judge_coverage(structured: dict, candidates: list[dict]) -> list[dict]:
    """후보 전체를 한 번의 호출로 채점한다.

    후보마다 따로 부르면 지연이 후보 수만큼 늘고, 절대 점수가 불안정하다.
    나란히 놓고 비교하게 하면 상대 순위가 훨씬 안정적이다.
    """
    if not candidates:
        return []
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": build_judge_prompt(structured, candidates)},
        ],
        "temperature": 0,
        "max_tokens": 2000,
    }
    raw = _post(UPSTAGE_CHAT_URL, payload, timeout=60)["choices"][0]["message"]["content"]
    verdicts = parse_json_safe(raw, [])
    if isinstance(verdicts, dict):
        verdicts = verdicts.get("results") or [verdicts]

    by_index = {int(v.get("candidate", 0)): v for v in verdicts if isinstance(v, dict)}
    results = []
    for index, case in enumerate(candidates, start=1):
        verdict = by_index.get(index, {})
        category = verdict.get("category")
        if category not in CATEGORY_SCORES:
            category = "not_covered"
        matched = [a for a in (verdict.get("matched_axes") or []) if a in AXIS_IDS]
        results.append({
            "case": case,
            "category": category,
            "coverage": coverage_score(category, matched, structured),
            "matched_axes": matched,
            "key_difference": as_text(verdict.get("key_difference")),
        })
    return results


def decide(category: str, score: float) -> str:
    """목표 플로우의 3분기.

    범주가 천장을, 점수가 바닥을 정한다. 점수만으로 분기하면 'partial인데 축이 많이
    맞아 확정'처럼 범주와 어긋나는 판정이 나온다. partial은 아무리 높아도 확인을 거친다.
    """
    if category == "covered" and score >= COVERAGE_CERTAIN:
        return "confirmed"
    if category in ("covered", "partial") and score >= COVERAGE_UNCERTAIN:
        return "needs_confirm"
    return "insufficient"


def search_similar_cases(structured: dict) -> dict:
    """구조화된 상황 → 유사 사례 판정. chat.py가 부르는 진입점.

    반환: {"decision": confirmed|needs_confirm|insufficient, "coverage": float, "results": [...]}
    검색이나 판정이 실패하면 insufficient로 떨어뜨린다. 못 찾은 것을 사기 확정으로
    잘못 넘기는 것보다, 기관에 직접 확인하게 안내하는 편이 안전하다.
    """
    empty = {"decision": "insufficient", "coverage": 0.0, "results": []}
    if not query_text(structured).strip():
        return empty
    try:
        recalled = recall_cases(structured)
        candidates = dedupe_cases(recalled, JUDGE_TOP_N)
        judged = judge_coverage(structured, candidates)
    except MissingUpstageAPIError:
        raise
    except Exception:
        return empty

    judged.sort(key=lambda r: (r["coverage"], r["case"].get("score", 0)), reverse=True)
    top = judged[:FINAL_TOP_K]
    if not top:
        return empty
    return {
        "decision": decide(top[0]["category"], top[0]["coverage"]),
        "coverage": top[0]["coverage"],
        "results": top,
    }


def format_case_for_user(result: dict) -> str:
    """0.6~0.8 구간에서 사용자에게 보여줄 후보 카드. 헤드라인 + 공식 링크 + 일치 근거."""
    case = result["case"]
    labels = {db: label for db, label, _ in AXES}
    axes = ", ".join(labels[a] for a in result["matched_axes"]) or "일부 정황"

    lines = [
        f"찾아본 것 중 지금 상황과 가장 비슷한 사례예요. 이 사례와 **{axes}**가 일치해요.",
        "",
        f"**{as_text(case.get('headline_ko')) or '유사 사례'}**",
    ]
    if as_text(case.get("modus_operandi_ko")):
        lines.append(as_text(case["modus_operandi_ko"]))
    if as_text(case.get("warning_signs")):
        lines.append("\n- 이런 말 나오면 의심: " + as_text(case["warning_signs"]))
    if result["key_difference"]:
        lines.append(f"- 다른 점: {result['key_difference']}")
    url = as_text(case.get("article_url")) or as_text(case.get("google_news_url"))
    if url:
        lines.append(f"\n관련 기사: {url}")
    lines += ["", "지금 겪고 계신 상황이 이거랑 비슷한가요? **예 / 아니오**로 답해 주세요."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ③ 피해 단계 진단
# ---------------------------------------------------------------------------

DAMAGE_STAGES = ("접촉초기", "개인정보제공", "링크클릭앱설치", "입금송금")

# 진행이 많이 된 단계가 앞에 온다. 첫 번째로 걸리는 것이 답이다.
_STAGE_MARKERS = [
    ("입금송금", ("송금", "이체", "입금", "보냈", "결제", "환전", "충전", "납입", "상품권")),
    ("링크클릭앱설치", ("링크", "url", "주소", "클릭", "눌렀", "접속", "설치", "앱", "apk", "원격")),
    ("개인정보제공", ("주민", "신분증", "계좌번호", "비밀번호", "인증번호", "otp", "개인정보", "알려줬", "입력")),
]

def classify_damage_stage(structured: dict) -> str:
    """이미 한 행동(taken_action)으로만 단계를 정한다. 근거가 없으면 빈 문자열.

    추측하지 않는다. 단계는 가이드 전체를 가르는 값이라 잘못 잡으면 엉뚱한 안내가
    통째로 나간다. LLM 에 맡겨 봤더니 요구받은 행동을 한 행동으로 오인해 과잉 진단이
    났다. 모르면 비워 두고 사용자에게 직접 묻는 편이 정확하고 단순하다.
    """
    actions = as_text(structured.get("taken_action")).lower()
    if actions:
        for stage, markers in _STAGE_MARKERS:
            if any(m in actions for m in markers):
                return stage
        return "접촉초기"   # 한 행동은 있지만 어느 표지에도 안 걸린다 = 아직 초기

    # 비어 있을 때는 '아직 못 들었다'와 '한 게 없다고 확인됐다'를 갈라야 한다.
    # 이 구분이 없으면 "아무것도 안 했어"라고 답한 사용자에게 같은 질문을 되풀이한다.
    if "taken_action" in (structured.get("unknown_fields") or []):
        return ""
    return "접촉초기"


# 사용자에게 보여줄 단계 설명. 내부 코드값("링크클릭앱설치")은 읽히지 않는다.
STAGE_LABELS = {
    "접촉초기": "연락만 받았고, 아직 아무것도 주거나 누르지 않은 단계",
    "개인정보제공": "이름·주민번호·계좌번호 같은 개인정보를 넘긴 단계",
    "링크클릭앱설치": "링크를 누르거나 앱을 설치한 단계",
    "입금송금": "이미 돈을 보낸 단계",
}

# 단계 확인을 몇 번까지 되묻는가. 이 횟수를 넘기면 더 묻지 않고 사용자가 마지막으로
# 설명한 내용으로 진단해 가이드로 넘어간다. 판정이 같은 단계를 고집할 때 사용자가
# 빠져나갈 길이 없으면 안 된다.
MAX_STAGE_CHECK_ROUNDS = 3

# 단계를 못 정했을 때 사용자에게 보여줄 선택지.
STAGE_OPTIONS = "\n".join(f"- {STAGE_LABELS[k]}" for k in DAMAGE_STAGES)


def coverage_signals(results: list[dict]) -> list[str]:
    """판정에서 실제로 일치한 축을 사용자 값으로 되돌려 위험 신호로 쓴다.

    LLM 을 새로 부르지 않는다. 어느 점이 알려진 수법과 겹치는지는 2단계 판정이 이미
    matched_axes 로 내놓았고, 그게 곧 위험 신호다. 따로 생성하면 호출이 늘고 근거가
    판정과 어긋난다.
    """
    labels = {db: label for db, label, _ in AXES}
    fields = {db: user_field for db, _, user_field in AXES}
    top = results[0] if results else {}
    signals = []
    for axis in top.get("matched_axes", []):
        value = as_text(top.get("_structured", {}).get(fields[axis]))
        signals.append(f"{labels[axis]} · {value}" if value else labels[axis])
    return signals


def make_stage_check(structured: dict, results: list[dict], stage: str) -> str:
    """위험 신호와 피해 단계를 보여주고 맞는지 묻는 문안. LLM 호출 없음."""
    for r in results[:1]:
        r["_structured"] = structured
    signals = coverage_signals(results)

    lines = ["지금 상황에서 이런 점이 알려진 사기 수법과 겹쳐요.", ""]
    lines += [f"- {sign}" for sign in signals] or ["- 상대가 밝힌 소속과 요구한 행동"]

    if stage:
        lines += ["", f"그리고 지금은 **{STAGE_LABELS[stage]}**로 보여요.", "",
                  "맞으면 **맞아요**, 다르면 무엇이 다른지 편하게 말씀해 주세요."]
    else:
        lines += ["", "이 중에 이미 하신 게 있나요? 해당하는 것을 말씀해 주세요.", "",
                  STAGE_OPTIONS, "",
                  "아직 아무것도 안 하셨다면 그렇게 말씀해 주세요."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# ④-A 대응 가이드와 도구
# ---------------------------------------------------------------------------

GUIDE_INTRO_SYSTEM = """사용자의 상황에 공감하는 문장 1~2개를 한국어로 써라.
- 사용자를 탓하지 말 것. "당황스러우셨겠어요" 같은 톤
- 사기 확정 단정 금지. "위험 신호가 보여요" 수준까지만
- 이어서 구체적 행동 안내가 나올 것이므로, 행동 지시는 쓰지 말 것
- 2문장 이내, 순수 텍스트만"""


def make_guide(stage: str, chat_messages: list[dict]) -> str:
    """공감 도입부 한두 문장 + 단계별 고정 가이드 + 도구 3종을 쓰는 법.

    도입부도 대화를 기록으로 넘긴다. messages 로 그대로 주면 모델이 직전 어시스턴트
    메시지의 형식을 따라 해, 단계 확인 화면의 위험 신호 목록을 그대로 반복한다.

    마무리(resolve_closing)까지 여기서 붙이는 것은, 이 메시지가 대화의 종착점이기
    때문이다. 화면 아래 버튼 3개만 덩그러니 두면 무엇부터 눌러야 할지 알 수 없다.
    쓰는 순서가 단계마다 갈리므로 마무리도 단계별로 다르다.
    """
    intro = call_llm(
        GUIDE_INTRO_SYSTEM,
        [{"role": "user", "content": "--- 대화 기록 ---\n" + transcript_of(chat_messages)}],
        temperature=0.7,
    )
    return "\n\n".join([
        intro.strip(),
        guide_templates.resolve(stage),
        guide_templates.resolve_closing(stage),
    ])


# 세 도구에 공통으로 붙는 머리말.
#
# 산출물의 화자는 챗봇이 아니라 사용자 본인이다. 이걸 명시하지 않으면 모델이 대화의
# 다음 차례로 알아듣고 "안녕하세요, 텅장지키미예요"라고 자기를 소개하거나, 문서 대신
# 상담 조언을 이어 쓴다.
TOOL_COMMON = """당신은 사용자가 쓸 문서를 대신 작성하는 도구다. 대화의 상대역이 아니다.

- 문서의 주체는 사용자 본인이다. 챗봇 이름('텅장지키미')이나 상담사 정체를 절대 쓰지 마라.
- 사용자에게 말을 걸거나, 조언하거나, 되묻지 마라. 요청받은 문서만 출력하라.
- 대화를 이어서 답하지 마라. 대화 기록은 사실을 뽑아 쓸 자료일 뿐이다.
- 대화 기록의 '상담봇'은 이 서비스이지 사건의 상대방이 아니다. 문서에 등장시키지 마라.
  보존·신고할 증거는 사기 의심자와 주고받은 것이지 이 상담 기록이 아니다.
- 대화 기록에 없는 사실을 지어내지 마라."""

TOOL_SYSTEMS = {
    "call_script": """사용자가 은행·경찰에 신고 전화할 때 수화기에 대고 그대로 읽을
대본만 써라.

출력은 대본 본문뿐이다. 사용자는 이 화면을 보면서 소리 내어 읽는다. 읽을 수 없는
것은 넣지 마라 — 제목, 머리말, 상황 해설, 조언, 행동 지시 목록, 사용자에게 되묻는
질문 전부 금지다. 특히 마지막에 "해당되는 게 있으면 알려주세요" 같은 질문을 붙이지
마라. 이 화면 다음에는 답을 받을 곳이 없다.

말하는 순서대로 담을 것 (자연스러운 구어체, 문단 사이는 빈 줄로만 구분):
① 첫마디 — 본인 소개와 용건 한 문장
② 피해 내용 — 언제, 어떤 경로로, 상대가 누구라고 했고, 무엇을 요구받았고,
   무엇을 제공하거나 송금했는지. 대화에서 확인된 사실만.
③ 요청 사항 — 판정된 피해 단계에 맞는 것(지급정지·피해구제 신청 등).
   아직 아무것도 제공하지 않은 단계라면 신고·상담 접수와 확인 요청까지만 말한다.

대화에 없는 사실(금액, 날짜, 계좌번호, 이름)은 지어내지 말고 [직접 입력] 으로 둔다.
전화를 거는 사람은 본인이다. 연락 경로나 시각처럼 본인이 당연히 아는 것을
"확인하지 못했습니다"라고 말하지 말고, 대화에 없으면 [직접 입력] 으로 둔다.
마크다운 표기(**, -, #, 번호 목록)를 쓰지 마라.""",
    "report": """피해 상황 요약 리포트를 써라. 신고·상담 시 제출용.
형식: 사건 개요(3줄 이내) / 시간 순 경과 / 상대방 정보(알려진 것만) /
제공·송금한 것 / 감지된 위험 신호 목록
대화에 없는 정보는 [확인 필요]로 표시. 추측 금지.""",
    "checklist": """증거 보존 체크리스트를 써라. 체크박스(- [ ]) 형식.
항목: 대화 캡처(날짜 보이게), 상대 프로필/계정 캡처, 송금 내역 캡처,
통화 녹음 백업, 상대 계좌·전화번호 기록, 주고받은 원본 대화 삭제 금지 안내
사용자 상황(피해 단계)에 맞는 항목 위주로 6~10개.

증거 보존을 이유로 피해를 키우는 행동을 절대 시키지 마라. 특히:
- 악성앱 삭제, 비행기 모드 전환, 카드 정지, 지급정지는 캡처보다 먼저다.
  "지우기 전에 캡처하세요" 같은 항목을 쓰지 마라. 앱은 이름만 적어 두면 된다.
- 상대와의 연락을 유지하거나 증거를 더 받아내려 대화를 이어가게 하지 마라.
'삭제 금지'는 이미 가지고 있는 문자·대화·거래내역 원본에만 해당한다.""",
}


def make_tool(tool: str, stage: str, chat_messages: list[dict]) -> str:
    """대응 도구 3종을 만든다.

    대화를 messages 로 그대로 넘기면 모델이 그 대화의 다음 차례로 알아듣는다. 그러면
    챗봇 말투로 조언을 이어 쓰거나 스스로를 '텅장지키미'라고 소개해 버린다. 산출물의
    화자는 챗봇이 아니라 사용자이므로, 대화는 한 덩어리 '자료'로 넘긴다.
    """
    transcript = transcript_of(chat_messages)
    prompt = (
        f"판정된 피해 단계: {stage}\n\n"
        "아래는 피해자와 상담봇이 나눈 대화 기록이다. 사실을 뽑아 쓸 자료이며,\n"
        "이 대화를 이어서 말하는 것이 아니다.\n\n"
        f"--- 대화 기록 시작 ---\n{transcript}\n--- 대화 기록 끝 ---"
    )
    return call_llm(
        TOOL_COMMON + "\n\n" + TOOL_SYSTEMS[tool],
        [{"role": "user", "content": prompt}],
        temperature=0.4,
    )


# ---------------------------------------------------------------------------
# ④-B 판단 근거가 부족할 때 — 기관에 직접 확인하는 대본
# ---------------------------------------------------------------------------

AGENCY_INQUIRY_SYSTEM = """사용자가 받은 연락이 진짜인지 확인하려고 상대 기관·회사에
직접 전화할 때 그대로 읽을 대본을 쓴다. 그리고 어디로 걸어야 하는지 갈래를 고른다.

아직 사기로 판정된 상황이 아니다. 정상적인 연락일 가능성이 충분히 있다.
사칭·사기·피싱으로 단정하는 표현을 쓰지 말고, 받은 내용을 그대로 옮겨
"이런 연락을 실제로 보내셨는지"를 사실만 놓고 묻게 한다.

출력은 아래 JSON 하나만. 다른 텍스트 금지.
{"category": "...", "script": "..."}

category — 확인 전화를 걸 상대의 종류. 다섯 중 하나만 고른다.
  "public"  검찰·경찰·법원·시청·구청·공단 등 공공기관과 그 산하 센터
  "finance" 은행·카드사·증권사·보험사·대부업체 등 금융회사
  "seller"  개인 판매자, 투자업체, 쇼핑몰, 낯선 계좌의 명의자
  "person"  지인·가족·연인 등 원래 아는 사람
  "unknown" 상대가 밝힌 소속이 없거나 위 넷으로 판단할 수 없음

script — 전화로 그대로 읽을 대화체 문단. 3~5문장. 마크다운·불릿·번호 금지.
  아래 다섯을 빠짐없이 담는다. 상대가 사실을 확인해 주려면 전부 필요하다.
    ① 본인 소개와 용건 — 사실 확인차 전화했다는 것
    ② 언제, 어떤 경로로 연락을 받았는지
    ③ 상대가 밝힌 소속·이름을 들은 그대로
    ④ 어떤 명목이었고 무엇을 요구받았는지 (금액·송금수단이 있으면 함께)
    ⑤ 확인 질문으로 마무리. 상대가 기관·회사면 그쪽에서 보낸 연락이 맞는지와
      그런 절차가 실제로 있는지까지 묻고, 아는 사람이면 본인이 보낸 게 맞는지만 묻는다.
      (가족에게 '그런 절차가 있느냐'고 묻는 말은 쓰지 않는다.)
  '사용자 정보'에 없는 사실은 지어내지 말고 [직접 입력] 으로 표시한다.
  자리표시자는 반드시 [직접 입력] 만 쓴다. [이름] 같은 다른 표기를 만들지 않는다.
  날짜·시각은 정보에 없으므로 항상 [직접 입력] 으로 둔다."""

# 대본에 넘길 재료. user_modus_operandi 는 일부러 뺐다. 그 문장에는 구조화 단계에서
# 이미 "사칭해 접근했고" 같은 단정이 섞여 들어가, 프롬프트로 아무리 중립을 지시해도
# 재료 자체가 상대를 범인으로 규정해 버린다. 축별 사실만 따로 넘긴다.
_INQUIRY_FIELDS = [
    ("contact_channel", "연락받은 경로"),
    ("stated_identity", "상대가 밝힌 소속·이름"),
    ("key_context", "연락 명목"),
    ("requested_action", "요구받은 행동"),
    ("money_method", "요구받은 금전·결제 방식"),
    ("taken_action", "사용자가 이미 한 행동"),
]

INQUIRY_CATEGORIES = ("public", "finance", "seller", "person", "unknown")

# LLM 호출이 실패해도 4-B 는 나가야 한다. 대본이 없으면 화면에 빈 칸이 남는다.
FALLBACK_INQUIRY_SCRIPT = (
    "안녕하세요, 사실 확인차 전화드렸습니다. [직접 입력]에 그쪽 이름으로 연락을 받았는데, "
    "실제로 보내신 연락이 맞는지 확인하고 싶습니다. 연락에 적힌 내용대로 진행하는 절차가 "
    "실제로 있는지도 알려주시면 감사하겠습니다."
)


def _inquiry_context(structured: dict) -> str:
    lines = [
        f"- {label}: {as_text(structured.get(field))}"
        for field, label in _INQUIRY_FIELDS
        if as_text(structured.get(field))
    ]
    return "\n".join(lines) or "- (확인된 정보 없음)"


def _contact_section(category: str, identity: str) -> tuple[str, str]:
    """보여줄 연락처 블록과 '다른 경우라면' 한 줄 목록을 만든다.

    고른 갈래를 펼쳐 맨 위에 놓되 나머지도 한 줄씩 남긴다. 분류가 빗나갔을 때
    사용자가 맞는 번호로 되찾아갈 길이 없으면 안 되기 때문이다.

    공공기관·금융사·판매자는 목록의 대표번호가 '그 기관'의 번호가 아닌 경우가 많다.
    상대 이름을 아는 한 공식 번호를 찾는 방법을 먼저 준다. 4-B 가 실제로 시키려는
    행동이 그것이다.
    """
    blocks = []
    if category != "person" and identity:
        blocks.append(guide_templates.LOOKUP_GUIDE.format(identity=identity))
    elif category == "unknown":
        blocks.append(guide_templates.LOOKUP_GUIDE_UNKNOWN)
    if category in guide_templates.CONTACT_BLOCKS:
        blocks.append(guide_templates.CONTACT_BLOCKS[category])

    others = [text for key, text in guide_templates.SHORT_ROUTES.items() if key != category]
    other_routes = "▸ 다른 경우라면\n" + "\n".join(f"  {t}" for t in others)
    return "\n\n".join(blocks), other_routes


def make_agency_inquiry_script(structured: dict) -> tuple[str, str]:
    """사기로 단정할 수 없을 때 주는 안내(4-B). (안내문, 전화 대본) 을 돌려준다.

    한 번의 호출로 대본과 갈래를 함께 받는다. 번호는 LLM 이 만들지 않는다 —
    guide_templates 에 하드코딩된 것만 쓰고, LLM 은 어느 갈래인지 고르기만 한다.
    지어낸 번호를 주면 사용자가 엉뚱한 상대에게 자기 상황을 그대로 설명하게 된다.

    대본을 안내문에 섞지 않고 따로 돌려주는 것은, 화면에서 '📞 신고 전화 대본'
    버튼을 눌렀을 때만 내보내기 위해서다. LLM 호출은 여기서 한 번뿐이므로
    버튼을 누르는 시점에 다시 부르지 않는다.
    """
    raw = call_llm(
        AGENCY_INQUIRY_SYSTEM,
        [{"role": "user", "content": "사용자 정보:\n" + _inquiry_context(structured)}],
        temperature=0.4,
    )
    data = parse_json_safe(raw, {})
    if not isinstance(data, dict):
        data = {}

    category = data.get("category")
    if category not in INQUIRY_CATEGORIES:
        category = "unknown"
    script = as_text(data.get("script")).strip() or FALLBACK_INQUIRY_SCRIPT

    identity = as_text(structured.get("stated_identity"))
    contact_block, other_routes = _contact_section(category, identity)
    guide = guide_templates.SELF_CHECK_GUIDE.format(
        contact_block=contact_block,
        other_routes=other_routes,
    )
    return guide, script
