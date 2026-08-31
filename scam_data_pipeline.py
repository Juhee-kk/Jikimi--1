"""사기 사례 RAG 데이터 파이프라인.

수집 → 구조화 → 색인의 3단계다.

  1) collect    Google News 검색 RSS와 공식기관 RSS에서 기사를 모으고, 원문 페이지에서
                본문까지 받아 data/raw_articles.jsonl 에 쌓는다.
  2) structure  raw 기사를 LLM으로 읽어 정해진 필드로 구조화해
                data/structured_scam_articles.jsonl 에 쌓는다.
  3) embed      공식 시나리오(사람이 직접 정리) + 구조화 자료를 같은 스키마로 정규화하고
                임베딩해 Qdrant에 올린다.

**구조화 결과가 어떤 필드로 이루어지는지는 아래 SCHEMA 한 곳만 보면 된다.**
프롬프트에 넣을 필드 목록, 타입 정규화 대상, 임베딩 텍스트 구성, Qdrant 페이로드가
전부 그 표에서 파생된다.

정기 실행:
    python scam_data_pipeline.py collect --limit 20     # 6시간마다 (collect.yml)
    python scam_data_pipeline.py structure              # 하루 1회 (process.yml)
    python scam_data_pipeline.py embed
    python scam_data_pipeline.py run --verbose          # 위 셋을 한 번에

일회성 보정:
    python scam_data_pipeline.py backfill-bodies        # 기존 raw에 본문 채우기
    python scam_data_pipeline.py restructure            # 본문 생긴 기사만 다시 구조화
    python scam_data_pipeline.py repair-headlines       # headline_ko를 원문 제목으로 복구
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import os
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

# ---------------------------------------------------------------------------
# 경로 / 환경
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

RAW_JSONL = DATA_DIR / "raw_articles.jsonl"
STRUCTURED_JSONL = DATA_DIR / "structured_scam_articles.jsonl"
OFFICIAL_SCENARIOS_JSONL = DATA_DIR / "official_scenarios.jsonl"
TAXONOMY_JSON = DATA_DIR / "taxonomy" / "scam_taxonomy.json"

# 되돌릴 일에 대비한 사본 보관소. 실행할 때마다 시각을 붙여 쌓으므로 이전 백업을
# 덮어쓰지 않는다. 용량만 차지하는 로컬 자료라 git에는 올리지 않는다(.gitignore).
BACKUP_DIR = DATA_DIR / "backup"

CURRENT_SCHEMA_VERSION = 3
DEFAULT_TAXONOMY_VERSION = "2026-08-25"


def load_dotenv(path: Path | None = None) -> None:
    candidates = [path] if path else [Path(".env"), BASE_DIR / ".env"]
    for candidate in candidates:
        if not candidate or not candidate.exists():
            continue
        with candidate.open("r", encoding="utf-8") as file:
            for raw_line in file:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value


load_dotenv()


# Streamlit Cloud 는 .env 를 못 본다(gitignore 대상이라 배포본에 아예 없다). 대신
# 대시보드 Settings → Secrets 에 넣은 값을 st.secrets 로만 내준다. 반대로 CI 와
# 로컬 CLI 에는 streamlit 실행 맥락이 없다. 세 환경을 한 함수로 흡수한다.
_secrets_unavailable = False


def get_secret(name: str, default: str | None = None) -> str | None:
    """설정값을 Streamlit secrets → 환경변수(.env 포함) 순으로 찾는다.

    환경마다 키를 주는 방법이 다르다.
      Streamlit Cloud : 대시보드 Settings → Secrets   (st.secrets 로만 읽힌다)
      로컬            : 셸 export 또는 .env
      GitHub Actions  : workflow 의 env:

    st.secrets 는 secrets.toml 이 없으면 조회 자체가 StreamlitSecretNotFoundError 를
    던진다. .get() 도 `in` 도 마찬가지라 예외로 감싸는 것 말고는 확인할 방법이 없다.
    로컬과 CI 에는 그 파일이 없으므로 이 처리가 빠지면 두 환경이 바로 깨진다.
    streamlit 이 설치되지 않은 환경도 있을 수 있어 import 까지 함께 보호한다.
    """
    global _secrets_unavailable
    if not _secrets_unavailable:
        try:
            import streamlit as st

            value = st.secrets[name]
        except KeyError:
            pass  # secrets 는 있는데 이 키만 없다. 환경변수로 넘어간다.
        except Exception:
            # secrets.toml 이 없거나 streamlit 이 없다. 이 프로세스에서는 다시 묻지 않는다.
            _secrets_unavailable = True
        else:
            text = str(value).strip()
            if text:
                return text
    return os.environ.get(name) or default


UPSTAGE_CHAT_URL = "https://api.upstage.ai/v1/chat/completions"
UPSTAGE_EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"
UPSTAGE_STRUCTURING_MODEL = get_secret("UPSTAGE_STRUCTURING_MODEL", "solar-mini")
UPSTAGE_EMBEDDING_MODEL = get_secret("UPSTAGE_EMBEDDING_MODEL", "embedding-passage")

QDRANT_URL = get_secret(
    "QDRANT_URL",
    "https://32cd9c82-9cec-491c-acc9-fbd57c385e1b.sa-east-1-0.aws.cloud.qdrant.io",
)
QDRANT_COLLECTION = get_secret("QDRANT_COLLECTION", "0818")
QDRANT_VECTOR_SIZE = int(get_secret("QDRANT_VECTOR_SIZE", "4096"))


# ---------------------------------------------------------------------------
# 스키마 — 이 파일에서 가장 먼저 볼 곳
#
# 필드를 추가하거나 용도를 바꾸려면 SCHEMA만 고치면 된다. 아래가 전부 여기서 파생된다.
#   NEWS_LLM_FIELDS       LLM에게 뽑아달라고 요청하는 필드 (프롬프트에 그대로 나열됨)
#   ARRAY/BOOLEAN_FIELDS  normalize_structured()가 타입을 강제하는 대상
#   VECTOR_TEXT_FIELDS    임베딩 텍스트에 들어가는 필드와 한글 라벨
#   PAYLOAD/FILTER/DISPLAY_FIELDS   Qdrant 페이로드의 3개 층
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Field:
    """구조화 스키마의 필드 하나.

    filled_by:
      "llm"      — 모델이 기사를 읽고 채운다. NEWS_LLM_FIELDS로 프롬프트에 나열된다.
      "pipeline" — 수집 정보나 실행 환경에서 코드가 채운다. 모델은 관여하지 않는다.
      "derived"  — 색인 시점에 다른 값에서 계산해 페이로드에만 넣는다.
    """

    name: str
    kind: str                 # text | list | bool | int | float
    filled_by: str
    note: str
    vector_label: str = ""    # 비어있지 않으면 임베딩 텍스트에 이 라벨로 포함된다
    in_payload: bool = False  # Qdrant 페이로드 최상위 (조회용 평면 필드)
    in_filter: bool = False   # filter_metadata — 검색할 때 query_filter로 좁히는 값
    in_display: bool = False  # display_metadata — 사용자 화면에 보여줄 값


SCHEMA: tuple[Field, ...] = (
    # --- 사건의 내용: LLM이 기사에서 읽어낸다 ---------------------------------
    Field("summary_ko", "text", "llm", "기사 요약 한두 문장",
          vector_label="요약", in_payload=True, in_display=True),
    Field("article_type", "text", "llm", "사례 / 신종경보 / 기타",
          in_payload=True, in_filter=True),
    Field("category", "text", "llm", "taxonomy의 category id 하나",
          vector_label="카테고리", in_payload=True, in_filter=True),
    Field("scenario_tags", "list", "llm", "taxonomy의 scenario_tag id 0개 이상",
          vector_label="시나리오태그", in_payload=True, in_filter=True),
    Field("is_novel", "bool", "llm", "기존 분류로 설명되지 않는 신규·변종 수법인가",
          in_payload=True, in_filter=True),
    Field("novelty_evidence", "text", "llm", "is_novel=true로 본 근거 한 문장",
          in_display=True),

    # 사기범이 한 행동 3종. 사용자 상황과의 매칭이 이 값들 위에서 일어난다.
    Field("modus_operandi_ko", "text", "llm", "수법 전체를 서술한 문장",
          vector_label="수법", in_display=True),
    Field("lure_hook", "list", "llm", "사기범이 내세운 명목·미끼",
          vector_label="유인책", in_display=True),
    Field("victim_action_requested", "list", "llm", "사기범이 요구한 행동",
          vector_label="요구행동", in_filter=True),

    Field("approach_channel", "list", "llm", "접근 경로 (전화·문자·SNS 등)",
          vector_label="접근경로", in_filter=True),
    Field("impersonation_target", "list", "llm", "사칭한 대상",
          vector_label="사칭대상", in_filter=True),
    Field("payment_method", "list", "llm", "요구된 결제·송금 수단",
          vector_label="결제수단", in_filter=True),
    Field("target_demographic", "list", "llm", "표적이 된 집단",
          vector_label="대상층", in_filter=True, in_display=True),
    Field("is_youth_targeted", "bool", "llm", "청년층을 노린 수법인가 (뉴스 탭 필터)",
          in_payload=True, in_filter=True),

    # 화면에 그대로 노출되는 두 필드 (pages_files/news.py의 신종 수법 카드)
    Field("warning_signs", "list", "llm", '"이 말 나오면 의심하세요" 문구',
          vector_label="위험신호", in_display=True),
    Field("response_guide_ko", "text", "llm", '"이렇게 피해요" 대응 안내',
          in_display=True),

    Field("severity_score", "int", "llm", "1~3 심각도",
          in_payload=True, in_filter=True),
    Field("category_confidence", "float", "llm", "0~1 분류 확신도",
          in_payload=True, in_filter=True),

    # --- 출처와 이력: 코드가 채운다 -------------------------------------------
    # headline_ko는 일부러 llm이 아니다. 모델에게 제목을 다시 쓰게 했더니 원문이
    # 멀쩡한데도 한국어가 깨진 행이 392건 중 25건 나왔다. 원문 title을 그대로 복사한다.
    Field("headline_ko", "text", "pipeline", "원문 기사 제목 (그대로 복사)",
          vector_label="제목", in_payload=True, in_display=True),
    Field("raw_article_id", "text", "pipeline", "raw_articles.jsonl의 id. point_id의 근거",
          in_payload=True, in_display=True),
    Field("article_url", "text", "pipeline", "원문 기사 주소",
          in_payload=True, in_display=True),
    Field("google_news_url", "text", "pipeline", "구글 뉴스 경유 주소 (원문과 다를 때만)",
          in_display=True),
    Field("article_published_at", "text", "pipeline", "기사 발행 시각 ISO",
          in_payload=True, in_filter=True),
    Field("source", "text", "pipeline", "수집 피드 이름",
          in_payload=True, in_filter=True, in_display=True),
    Field("source_kind", "text", "pipeline", "news / rss_notice / official_scenario",
          in_payload=True, in_filter=True, in_display=True),
    Field("publisher", "text", "pipeline", "발행 매체",
          in_payload=True, in_filter=True, in_display=True),
    Field("structured_at", "text", "pipeline", "구조화한 시각",
          in_filter=True),
    Field("llm_model", "text", "pipeline", "구조화에 쓴 모델"),
    Field("taxonomy_version", "text", "pipeline", "적용한 taxonomy 판",
          in_payload=True, in_filter=True),
    Field("schema_version", "int", "pipeline", "스키마 판",
          in_payload=True, in_filter=True),

    # --- 색인 시점에 계산 ------------------------------------------------------
    Field("article_published_date", "text", "derived", "발행일 (날짜만)", in_payload=True),
    Field("article_published_year", "int", "derived", "발행 연도", in_payload=True),
    Field("article_published_month", "int", "derived", "발행 월", in_payload=True),
)

FIELDS_BY_NAME = {field.name: field for field in SCHEMA}

# LLM에게 요청하는 필드. 프롬프트에 이 순서 그대로 나열된다.
NEWS_LLM_FIELDS = [f.name for f in SCHEMA if f.filled_by == "llm"]

# normalize_structured()의 타입 강제 대상
ARRAY_FIELDS = {f.name for f in SCHEMA if f.kind == "list"}
BOOLEAN_FIELDS = {f.name for f in SCHEMA if f.kind == "bool"}

# 임베딩 텍스트 구성 (라벨, 필드명).
# 순서를 SCHEMA 선언 순서와 분리해 고정한다. 이 순서가 바뀌면 내용이 같아도 임베딩
# 텍스트가 달라져 이미 올라간 벡터를 전부 다시 만들어야 한다. 특히 손으로 정리한
# 공식 시나리오까지 재임베딩 대상이 되므로, 바꿀 이유가 없으면 건드리지 않는다.
VECTOR_TEXT_ORDER = (
    "headline_ko", "summary_ko", "category", "scenario_tags", "modus_operandi_ko",
    "approach_channel", "impersonation_target", "lure_hook", "victim_action_requested",
    "payment_method", "target_demographic", "warning_signs",
)
VECTOR_TEXT_FIELDS = [(FIELDS_BY_NAME[name].vector_label, name) for name in VECTOR_TEXT_ORDER]

_missing_vector_order = {f.name for f in SCHEMA if f.vector_label} - set(VECTOR_TEXT_ORDER)
assert not _missing_vector_order, f"VECTOR_TEXT_ORDER에 빠진 필드: {_missing_vector_order}"

# Qdrant 페이로드 3개 층
PAYLOAD_TOP_LEVEL_FIELDS = [f.name for f in SCHEMA if f.in_payload]
FILTER_METADATA_FIELDS = [f.name for f in SCHEMA if f.in_filter]
DISPLAY_METADATA_FIELDS = [f.name for f in SCHEMA if f.in_display]

ALLOWED_ARTICLE_TYPES = {"사례", "신종경보", "기타"}

# 예전 판에서 쓰던 한글 값 → 현재 taxonomy id
LEGACY_CATEGORY_ALIASES = {
    "기타": "other_known_scam",
    "신종": "novel_scam",
    "무관": "irrelevant",
}
LEGACY_ARTICLE_TYPE_ALIASES = {
    "예방교육": "기타",
    "정책단속": "기타",
    "통계": "기타",
}

# 공식 시나리오(사람이 정리한 자료)에 공통으로 붙는 값
OFFICIAL_DEFAULTS = {
    "source": "counterscam112_scenario",
    "source_kind": "official_scenario",
    "publisher": "피싱안심SOS",
    "structured_at": "2026-08-24T00:00:00+09:00",
    "taxonomy_version": "2026-08-24",
    "schema_version": CURRENT_SCHEMA_VERSION,
    "category_confidence": 1.0,
    "is_novel": False,
    "novelty_evidence": "공식 기준 사례로 정리된 기존 사기 시나리오",
}


# ---------------------------------------------------------------------------
# 검색용 텍스트
#
# 1단계 임베딩 검색은 아래 세 필드만 쓴다. 266건 실측 근거:
#   접근경로는 "전화" 하나가 44%를 덮어 일치해도 후보가 21% 남는 반면,
#   유인은 1.5%·요구행동은 2.2%까지 좁힌다. 변별력이 10배 넘게 차이난다.
# 셋을 함께 쓰는 이유는 서로의 결손을 메우기 때문이다.
#   - 유인/요구행동만 쓰면 둘 다 빈 51건(19%)이 검색 불가가 된다.
#   - 수법 문장만 쓰면 27%가 15자 미만이고 "전세사기" 같은 값은 4건이 완전히 겹친다.
# 골든셋 검증 결과 recall@30 6/6, 정답이 전부 1위.
# ---------------------------------------------------------------------------

RETRIEVAL_FIELDS = ("modus_operandi_ko", "lure_hook", "victim_action_requested")

# 검색 텍스트가 이보다 짧으면 사례를 특정할 수 없어 색인에서 뺀다.
MIN_RETRIEVAL_TEXT_CHARS = 25


# ---------------------------------------------------------------------------
# 수집 설정
#
# Google News는 검색어 기반이라 노이즈가 많아 1차 키워드 필터를 건다.
# KISA/금융위 RSS는 공식 출처라 전부 raw에 저장하고, structure 단계에서 판단한다.
# ---------------------------------------------------------------------------

MAX_SNIPPET_CHARS = 1200
MAX_BODY_CHARS = 2000

FEED_UA = "JikimiDataCollector/0.2 (+https://local)"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

GOOGLE_NEWS_QUERY_TERMS = ["신종 사기", "신종 피싱", "청년 사기"]
GOOGLE_NEWS_QUERY_LIMITS = {"신종 사기": 50, "신종 피싱": 50, "청년 사기": 50}

RSS_FEEDS = [
    {"source": "kisa_boho_security_notice", "url": "https://www.boho.or.kr/kr/rss.do?bbsId=B0000133"},
    {"source": "kisa_boho_report_guide", "url": "https://www.boho.or.kr/kr/rss.do?bbsId=B0000127"},
    {"source": "fsc_press_release", "url": "http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111"},
]

FRAUD_TERMS_STRONG = {
    "금융사기", "보이스피싱", "스미싱", "메신저피싱", "몸캠피싱", "큐싱",
    "로맨스스캠", "로맨스 스캠", "투자리딩방", "리딩방 사기", "투자사기", "투자 사기",
    "코인사기", "가상자산 사기", "중고거래 사기", "노쇼사기", "대출사기", "대출 빙자",
    "대포통장", "통장 대여", "악성앱", "악성 앱",
    "신종 사기", "신종 피싱", "청년 사기", "사칭 사기", "사칭 피싱",
}

FRAUD_TERMS_WEAK = {"사기", "피싱", "스캠", "사칭", "명의도용", "사기범", "사기단"}

MODUS_TERMS = {
    "미끼", "속여", "속아", "속인", "유인", "유도", "편취", "갈취", "수법",
    "피해자", "피해액", "주의", "예방", "신고", "급증", "기승", "확산",
    "신종", "변종", "조심", "설치", "송금", "이체", "가짜", "허위", "요구", "협박",
}

EXCLUDE_TERMS = {
    "사기 진작", "사기진작", "구속", "송치", "기소", "징역", "선고", "영장",
    "압수수색", "검거", "피소", "고발", "재판", "항소", "실형", "무죄",
}


# ---------------------------------------------------------------------------
# 공용 유틸
# ---------------------------------------------------------------------------


@dataclass
class RawArticle:
    id: str
    source: str
    source_kind: str
    feed_url: str
    title: str
    link: str
    rss_link: str
    publisher: str | None
    published_at: str | None
    summary_snippet: str
    fetched_at: str
    content_hash: str
    # 원문 페이지에서 받아온 본문. Google News RSS의 description은 제목만 담고 있어서
    # 이게 없으면 구조화가 제목 한 줄만 보고 값을 지어낸다.
    body_text: str = ""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ssl_context() -> ssl.SSLContext | None:
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = re.sub(r"<[^>]+>", " ", value)
    value = html.unescape(value)
    return re.sub(r"\s+", " ", value).strip()


def as_text(value: Any) -> str:
    """어떤 값이든 사람이 읽는 문자열로. 빈값 표기("없음", "[]")는 빈 문자열로 친다."""
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(text for item in value if (text := as_text(item)))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    text = str(value).strip()
    return "" if text in {"없음", "[]", "{}", "N/A", "null", "None"} else text


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [text for item in value if (text := as_text(item))]
    text = as_text(value)
    if not text:
        return []
    if "," in text:
        return [item.strip() for item in text.split(",") if item.strip()]
    return [text]


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = as_text(value).lower()
    if text in {"true", "yes", "y", "1", "청년", "해당"}:
        return True
    if text in {"false", "no", "n", "0", "미해당", "아니오"}:
        return False
    return False


def stable_hash(*parts: str) -> str:
    joined = "\n".join(part.strip().lower() for part in parts if part)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def strip_surrogate_chars(value: Any) -> Any:
    if isinstance(value, str):
        return "".join(char for char in value if not 0xD800 <= ord(char) <= 0xDFFF)
    if isinstance(value, list):
        return [strip_surrogate_chars(item) for item in value]
    if isinstance(value, dict):
        return {
            strip_surrogate_chars(key) if isinstance(key, str) else key: strip_surrogate_chars(item)
            for key, item in value.items()
        }
    return value


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_no, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} JSON 파싱 실패: {exc}") from exc
    return rows


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(strip_surrogate_chars(row), ensure_ascii=False) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """jsonl 전체를 덮어쓴다. 쓰다가 죽어도 원본이 남도록 임시파일에 쓴 뒤 교체한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(strip_surrogate_chars(row), ensure_ascii=False) + "\n")
    tmp_path.replace(path)


# 재시도할 상태 코드. 429(호출 한도)는 잠시 뒤 다시 걸면 대개 통과한다.
RETRY_STATUS = {408, 425, 429, 500, 502, 503, 504}
MAX_HTTP_RETRIES = int(get_secret("UPSTAGE_MAX_RETRIES", "5"))
# 연속 호출 간 최소 간격(초). 한도에 처음부터 안 걸리게 속도를 낮춘다.
MIN_CALL_INTERVAL = float(get_secret("UPSTAGE_MIN_INTERVAL", "0.4"))

_last_call_at = 0.0


def _throttle() -> None:
    global _last_call_at
    wait = MIN_CALL_INTERVAL - (time.monotonic() - _last_call_at)
    if wait > 0:
        time.sleep(wait)
    _last_call_at = time.monotonic()


def http_json(
    url: str, body: dict[str, Any], api_key: str, timeout: int, verbose: bool = False
) -> dict[str, Any]:
    """Upstage API 호출. 429·5xx·네트워크 오류는 지수 백오프로 재시도한다.

    재시도가 없으면 호출 한도에 걸리는 순간 그 건이 그대로 실패로 남는다.
    (435건 재구조화에서 절반 이상이 429로 떨어진 적이 있다.)
    """
    payload = json.dumps(strip_surrogate_chars(body), ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None

    for attempt in range(1, MAX_HTTP_RETRIES + 1):
        _throttle()
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code not in RETRY_STATUS:
                raise
            # 서버가 알려준 대기 시간이 있으면 그것을 따른다.
            header = (exc.headers or {}).get("Retry-After")
            try:
                wait = float(header) if header else 0.0
            except ValueError:
                wait = 0.0
            wait = wait or min(60.0, 2.0 ** attempt)
        except (urllib.error.URLError, TimeoutError, ssl.SSLError, ConnectionError) as exc:
            last_error = exc
            wait = min(60.0, 2.0 ** attempt)

        if attempt == MAX_HTTP_RETRIES:
            break
        wait += random.uniform(0, 0.5 * wait)  # 여러 요청이 같은 순간에 몰리지 않게
        if verbose:
            print(f"  [재시도 {attempt}/{MAX_HTTP_RETRIES}] {wait:.1f}초 뒤 다시 시도: {last_error}",
                  file=sys.stderr, flush=True)
        time.sleep(wait)

    raise last_error  # type: ignore[misc]


def upstage_key() -> str:
    api_key = get_secret("UPSTAGE_API") or get_secret("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API 또는 UPSTAGE_API_KEY가 필요합니다.")
    return api_key


def looks_garbled(text: str | None) -> bool:
    """한국어 문장이 깨졌는지 대략 판정한다. 리포트·점검 용도로만 쓴다.

    실제로 관찰된 깨짐 두 가지를 본다.
      - 고립 자모: "서이ㄎ워ㄎ워ㄎ 3류들"
      - 한중일 한자·가나 혼입 3자 이상: "全豪明望特画球格会乶える"
    그 외에는 글자(숫자·구두점 제외) 중 한글 비율이 절반 미만이면 깨진 것으로 본다.
    """
    text = text or ""
    if re.search(r"[ㄱ-ㆎ]", text):
        return True
    letters = [char for char in text if char.isalpha()]
    if not letters:
        return False
    cjk = sum(1 for char in letters if "一" <= char <= "鿿" or "぀" <= char <= "ヿ")
    hangul = sum(1 for char in letters if "가" <= char <= "힣")
    return cjk >= 3 or hangul / len(letters) < 0.5


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


def load_taxonomy(path: Path = TAXONOMY_JSON) -> dict[str, Any]:
    if path.exists():
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    return {
        "taxonomy_version": DEFAULT_TAXONOMY_VERSION,
        "schema_version": CURRENT_SCHEMA_VERSION,
        "categories": [
            {
                "id": "irrelevant",
                "ko_name": "무관",
                "definition": "RAG 사례 검색에 사용할 수 없는 문서",
                "use_criteria": "사기와 무관하거나 정보가 부족한 경우",
            }
        ],
        "scenario_tags": [],
    }


def taxonomy_ids(taxonomy: dict[str, Any], key: str) -> list[str]:
    return [
        item["id"]
        for item in taxonomy.get(key, [])
        if isinstance(item, dict) and as_text(item.get("id"))
    ]


def format_taxonomy_items(items: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in items:
        item_id = as_text(item.get("id"))
        if not item_id:
            continue
        lines.append(
            f"- {item_id}: {as_text(item.get('ko_name'))}"
            f" / 정의: {as_text(item.get('definition')) or '없음'}"
            f" / 사용 기준: {as_text(item.get('use_criteria')) or '없음'}"
        )
    return "\n".join(lines) if lines else "- 없음"


# ---------------------------------------------------------------------------
# 1. 수집
# ---------------------------------------------------------------------------


def source_kind_for(source: str) -> str:
    if source == "counterscam112_scenario":
        return "official_scenario"
    if source.startswith("google_news:"):
        return "news"
    if source.startswith("kisa_") or source.startswith("fsc_"):
        return "rss_notice"
    return "unknown"


def parse_pub_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")


def child_text(item: ElementTree.Element, tag: str) -> str:
    child = item.find(tag)
    return child.text if child is not None and child.text else ""


def build_google_news_feeds() -> list[dict[str, Any]]:
    feeds: list[dict[str, Any]] = []
    for keyword in GOOGLE_NEWS_QUERY_TERMS:
        encoded = urllib.parse.urlencode({"q": keyword, "hl": "ko", "gl": "KR", "ceid": "KR:ko"})
        feeds.append(
            {
                "source": f"google_news:{keyword}",
                "url": f"https://news.google.com/rss/search?{encoded}",
                "limit": GOOGLE_NEWS_QUERY_LIMITS.get(keyword),
            }
        )
    return feeds


def resolve_google_news_url(link: str, timeout: int = 15) -> str:
    """news.google.com 경유 주소를 원문 주소로 되돌린다. 실패하면 원래 링크 그대로."""
    if "news.google.com" not in link:
        return link
    token = link.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
    headers = {"User-Agent": BROWSER_UA}
    try:
        request = urllib.request.Request(link, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            page = response.read().decode("utf-8", "replace")
        signature = re.search(r'data-n-a-sg="([^"]+)"', page).group(1)
        timestamp = re.search(r'data-n-a-ts="([^"]+)"', page).group(1)
        inner = json.dumps(
            [
                "garturlreq",
                [
                    ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1,
                     None, None, None, None, None, 0, 1],
                    "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0,
                ],
                token,
                int(timestamp),
                signature,
            ],
            separators=(",", ":"),
        )
        form = urllib.parse.urlencode(
            {"f.req": json.dumps([[["Fbv4je", inner, None, "generic"]]], separators=(",", ":"))}
        ).encode()
        request = urllib.request.Request(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data=form,
            headers={**headers, "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            raw = response.read().decode("utf-8", "replace")
        for chunk in re.finditer(r"^\[\[.*$", raw, flags=re.MULTILINE):
            for entry in json.loads(chunk.group(0)):
                if len(entry) > 2 and entry[1] == "Fbv4je" and isinstance(entry[2], str):
                    resolved = json.loads(entry[2])[1]
                    if isinstance(resolved, str) and resolved.startswith("http"):
                        return resolved
    except Exception:
        pass
    return link


# 본문이 아닌 영역. 네비게이션·광고·관련기사 목록이 섞이면 구조화가 엉뚱한 값을 만든다.
_BOILERPLATE_RE = re.compile(
    r"(?is)<(script|style|nav|header|footer|aside|form|iframe|noscript)[^>]*>.*?</\1>"
)
_BLOCK_RE = re.compile(r"(?i)</?(p|div|br|li|h[1-6]|tr|section|article)[^>]*>")

# 언론사 공통 상용구. 본문 예산(MAX_BODY_CHARS)을 갉아먹고 구조화에 노이즈가 된다.
_JUNK_LINE_RE = re.compile(
    r"Internet Explorer|최신 브라우저|자동요약|본문 보기를 권장|무단[ ]?전재|재배포[ ]?금지"
    r"|저작권자|ⓒ|기사제보|구독하기|카카오톡 공유|네이버에서 구독"
)


def extract_article_body(page: str) -> str:
    """기사 HTML에서 본문 문단만 추려낸다.

    시맨틱 마크업이 언론사마다 제각각이라 컨테이너를 특정하지 않고,
    '길고 한글 비중이 높은 줄'만 남기는 방식으로 메뉴·저작권 문구를 걸러낸다.
    걸러낸 뒤의 앞 MAX_BODY_CHARS 자를 쓴다(원문 앞부분이 아니다).
    """
    text = _BOILERPLATE_RE.sub(" ", page)
    text = _BLOCK_RE.sub("\n", text)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))

    lines = []
    for raw_line in text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if len(line) < 30 or _JUNK_LINE_RE.search(line):
            continue
        letters = [char for char in line if char.isalpha()]
        if not letters or sum(1 for c in letters if "가" <= c <= "힣") / len(letters) < 0.5:
            continue
        lines.append(line)

    body = "\n".join(dict.fromkeys(lines))  # 같은 문구 반복(요약+본문) 제거
    return body[:MAX_BODY_CHARS].strip()


def fetch_article_body(url: str, timeout: int = 12) -> str:
    """원문 페이지를 받아 본문을 추출한다. 실패하면 빈 문자열."""
    if not url.startswith("http"):
        return ""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
        with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
            raw = response.read(500_000)
            charset = response.headers.get_content_charset() or "utf-8"
        return extract_article_body(raw.decode(charset, "replace"))
    except Exception:
        return ""


def fetch_feed(feed: dict[str, Any], timeout: int = 15) -> list[RawArticle]:
    request = urllib.request.Request(feed["url"], headers={"User-Agent": FEED_UA})
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        xml_bytes = response.read()

    root = ElementTree.fromstring(xml_bytes)
    fetched_at = now_iso()
    rows: list[RawArticle] = []
    for item in root.findall(".//item"):
        title = clean_text(child_text(item, "title"))
        link = clean_text(child_text(item, "link"))
        summary = clean_text(child_text(item, "description"))[:MAX_SNIPPET_CHARS]
        source_tag = item.find("source")
        publisher = clean_text(source_tag.text) if source_tag is not None else ""
        content_hash = stable_hash(link, title)
        rows.append(
            RawArticle(
                id=content_hash[:16],
                source=feed["source"],
                source_kind=source_kind_for(feed["source"]),
                feed_url=feed["url"],
                title=title,
                link=link,
                rss_link=link,
                publisher=publisher or None,
                published_at=parse_pub_date(child_text(item, "pubDate")),
                summary_snippet=summary,
                fetched_at=fetched_at,
                content_hash=content_hash,
            )
        )
    return rows


def coarse_is_fraud_related(article: RawArticle) -> bool:
    """뉴스 검색 결과의 1차 필터. 공식 RSS에는 적용하지 않는다."""
    text = f"{article.title} {article.summary_snippet}".lower()
    has_modus = any(keyword in text for keyword in MODUS_TERMS)
    if any(keyword in text for keyword in EXCLUDE_TERMS) and not has_modus:
        return False
    if any(keyword.lower() in text for keyword in FRAUD_TERMS_STRONG):
        return True
    if any(keyword.lower() in text for keyword in FRAUD_TERMS_WEAK):
        return has_modus
    return False


def collect(
    limit: int | None = 20,
    timeout: int = 8,
    verbose: bool = False,
    resolve_urls: bool = True,
    fetch_bodies: bool = True,
) -> dict[str, Any]:
    feeds = [*build_google_news_feeds(), *RSS_FEEDS]
    seen = {row["content_hash"] for row in read_jsonl(RAW_JSONL) if row.get("content_hash")}
    new_rows: list[dict[str, Any]] = []
    fetched = 0
    errors: list[dict[str, str]] = []
    per_feed: dict[str, int] = {}

    for feed in feeds:
        feed_limit = feed.get("limit", limit)
        try:
            articles = fetch_feed(feed, timeout=timeout)
        except Exception as exc:
            errors.append({"source": feed["source"], "error": str(exc)})
            if verbose:
                print(f"[collect] 실패 {feed['source']}: {exc}", file=sys.stderr, flush=True)
            continue

        kept = 0
        for article in articles:
            fetched += 1
            if article.content_hash in seen:
                continue
            if article.source_kind == "news" and not coarse_is_fraud_related(article):
                continue
            seen.add(article.content_hash)
            if resolve_urls:
                article.link = resolve_google_news_url(article.link, timeout=timeout + 7)
            if fetch_bodies:
                article.body_text = fetch_article_body(article.link, timeout=timeout + 4)
                if verbose and not article.body_text:
                    print(f"[collect] 본문 실패: {article.link[:70]}", file=sys.stderr, flush=True)
            new_rows.append(asdict(article))
            kept += 1
            if verbose:
                print(f"[collect] {article.source}: {article.title[:70]}", flush=True)
            if feed_limit is not None and kept >= feed_limit:
                break
        per_feed[feed["source"]] = kept

    append_jsonl(RAW_JSONL, new_rows)
    return {
        "fetched": fetched,
        "saved": len(new_rows),
        "with_body": sum(1 for row in new_rows if row.get("body_text")),
        "path": str(RAW_JSONL),
        "per_feed": per_feed,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# 2. 구조화
# ---------------------------------------------------------------------------


def build_structuring_prompt(article: dict[str, Any]) -> str:
    taxonomy = load_taxonomy()
    category_ids = taxonomy_ids(taxonomy, "categories")
    scenario_tag_ids = taxonomy_ids(taxonomy, "scenario_tags")
    body = as_text(article.get("body_text"))
    material = f"본문:\n{body}" if body else f"요약: {article['summary_snippet']}"

    return f"""
너는 금융사기 사례 RAG를 위한 신규 자료 구조화 분류기다.
아래 수집 자료를 읽고 JSON 객체 하나만 출력해라. 설명 문장이나 markdown은 금지한다.

category 기준:
{format_taxonomy_items(taxonomy.get("categories", []))}

scenario_tags 기준:
{format_taxonomy_items(taxonomy.get("scenario_tags", []))}

필드:
{", ".join(NEWS_LLM_FIELDS)}

■ article_type 판정 — 두 조건을 모두 만족해야 "사례"다.
  (1) 실제 사기 사건이나 사기 시도가 있었고,
  (2) 그 정황이나 수법이 기사에 설명돼 있다.
- 둘 다 맞으면 "사례". 기사의 목적이 무엇이든(미담, 경고, 보도) 실제 사건의 수법이
  적혀 있으면 사례다. 사기를 막아낸 기사라도 어떤 수법이었는지 적혀 있으면 사례다.
  그중 기관이 새 수법을 공식 경고하는 형태면 "신종경보"로 둔다.
- 하나라도 어긋나면 "기타". 특히 **사기 사건 자체가 없는 기사는 무조건 기타**다.
  예방 교육·강좌 안내, 정책·제도 발표, 협약·행사, 기업의 보안 기능 출시,
  피해 건수 증감만 전하는 통계 보도가 여기 해당한다.
  이런 기사는 사기를 주제로 다룰 뿐 사기가 일어난 것이 아니다.
- 판단 순서: 먼저 "이 기사에 당한 사람 또는 당할 뻔한 사람이 있는가"를 보라.
  없으면 그 뒤는 볼 것도 없이 "기타"다.

■ 수법 필드는 **사기범이 한 행동**만 담는다 — 주어를 반드시 확인하라.
  기사에 등장하는 기관·기업·지자체·경찰이 한 일(교육 제공, 서비스 출시, 예방 조치,
  수사·검거)은 사기범의 행동이 아니다. 절대 아래 필드에 넣지 마라.
  사기범의 행동을 특정할 수 없으면 빈 값으로 둔다.
- lure_hook: 사기범이 피해자를 끌어들이려고 내세운 명목·미끼.
  기관이 제공하는 정상적인 교육·서비스·제도는 미끼가 아니다.
  수법 이름("피싱", "신종 사기")도 미끼가 아니다.
- victim_action_requested: 사기범이 피해자에게 하라고 요구한 행동.
  피해를 막기 위한 행동(확인, 신고, 점검, 교육 참여, 계약서 검토)은 요구가 아니다.
- modus_operandi_ko: 사기범이 어떻게 접근해 무엇을 요구했는지의 서술.
  기관의 대응이나 예방 활동을 수법으로 서술하지 마라.

■ is_novel 판정
- 위 category/scenario_tags 목록으로 설명되는 수법이면 false.
- **제목이나 본문에 "신종"이라는 낱말이 있다는 이유만으로 true를 주지 마라.**
  언론은 이미 흔한 수법에도 관용적으로 "신종"을 붙인다. 낱말이 아니라 내용으로 판단하라.
- true로 두려면 novelty_evidence에 '기존 분류 중 어느 것으로도 설명되지 않는 이유'를
  본문 근거로 한 문장 적어야 한다. 그걸 못 적겠으면 false다.

■ is_youth_targeted 판정
- 본문에 20대·30대·청년·대학생·취준생·사회초년생·신입사원이 피해자나 표적으로
  언급되면 true.
- 그런 언급이 없다면, 수법의 진입점이 청년에게 고유할 때만 true.
  (학자금·청년 정책자금, 생애 첫 전세, 대학가 아르바이트, 취업 준비 과정 등)
- 온라인·SNS·투자·중고거래라는 이유만으로 true를 주지 마라. 전 연령이 쓴다.

■ 화면에 그대로 노출되는 두 필드 — 비면 카드가 빈칸으로 나온다
- warning_signs: 피해자가 그 순간에 알아챌 수 있는 신호. 배열.
  이용자는 이 항목을 "이 말 나오면 의심하세요"로 읽는다. 따라서 **사기범이 한 말,
  사기범이 보인 행동, 사기범이 요구한 것** 중에서만 고른다.
  ★ 수법 이름을 넣지 마라. "노쇼사기", "보이스피싱", "로맨스스캠" 같은 범죄명은
    신호가 아니다. 사기범은 자기 입으로 그런 말을 하지 않으므로 피해자가 들을 수 없다.
    카테고리명·통계·기관의 대응도 마찬가지로 넣지 마라.
  ★ 낱말만 나열하지 말고 행위로 서술한다.
    "~라고 말한다", "~를 요구한다", "~하도록 유도한다" 처럼 무엇을 보면 알 수 있는지 쓴다.
  ★ 확인·신고·점검 같은 예방 행동은 신호가 아니라 대응이다. response_guide_ko에 쓴다.
  ★ lure_hook이나 modus_operandi_ko의 문장을 그대로 복사하지 마라.
    같은 사건을 다루더라도 "피해자가 무엇을 보고 알아채는가"의 관점으로 다시 쓴다.
  본문에 사기범의 발언이 인용돼 있으면 그 표현을 살린다.
  사기범의 말·행동을 특정할 수 없으면 빈 배열로 둔다.
- response_guide_ko: 이 수법을 마주쳤을 때 이용자가 취할 행동. 2문장 이내 평서문.
  본문이 대응·예방 방법을 제시하면 그것을 옮기고, 없으면 위 수법 서술에서
  차단 지점이 되는 행동을 쓴다. "주의하세요" 같은 일반론은 쓰지 마라.

■ 표기 규칙 (같은 값이 다르게 저장되면 검색 매칭이 깨진다)
- 조사·서술어를 떼고 명사구로 쓴다: "송금했다" → "송금"
- 띄어쓰기를 붙여 통일한다: "계좌 이체" → "계좌이체", "악성 앱" → "악성앱"
- 한 배열 안에 같은 뜻을 중복해 넣지 않는다: ["송금", "금전 송금"] → ["송금"]

■ 값을 지어내지 않기 (수집 자료가 제목 한 줄뿐인 경우가 있다)
- 위 category/scenario_tags 정의문의 문장을 값으로 옮겨 적지 마라. 그 정의는 태그를
  고르기 위한 기준일 뿐, 거기 적힌 진행 과정이 이 기사에 있었다는 뜻이 아니다.
- 사기를 막았다·검거했다·포상했다는 결과만 전하고 수법 상세가 없는 기사가 많다.
  수법이 무엇이었을지 추측해 전형적인 문장을 만들지 말고 비워 둬라.

규칙:
- category는 반드시 다음 중 하나만 선택한다: {", ".join(category_ids)}
- scenario_tags는 반드시 다음 중 0개 이상만 선택한다: {", ".join(scenario_tag_ids) if scenario_tag_ids else "등록된 태그 없음"}
- 같은 의미의 scenario tag를 새로 만들지 않는다.
- 기존 category/scenario_tags로 설명 가능하면 is_novel=false.
- 기존 기준으로 설명하기 어려운 신규·변종 수법이면 category=novel_scam, is_novel=true.
- 사기는 맞지만 기존 8개 category에 딱 맞지 않는 알려진 유형이면 category=other_known_scam.
- 사기 사례로 쓰기 어렵다면 category=irrelevant.
- 배열 필드는 배열로, 모르는 문자열 필드는 "없음", 모르는 배열 필드는 []로 채운다.
- category_confidence는 0~1, severity_score는 1~3 정수로 출력한다.

수집 자료:
제목: {article["title"]}
{material}
URL: {article["link"]}
발행일: {article.get("published_at") or "없음"}
출처: {article.get("source") or "없음"}
발행처: {article.get("publisher") or "없음"}
""".strip()


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
        if not match:
            raise
        return json.loads(match.group(0))


def normalize_structured(row: dict[str, Any], *, source_kind: str | None = None) -> dict[str, Any]:
    """LLM 출력이든 예전 판 저장분이든 같은 스키마로 맞춘다.

    taxonomy에 없는 category/tag를 버리고, SCHEMA가 선언한 타입을 강제한다.
    scam_feed(뉴스 탭)도 저장분을 읽을 때 이 함수를 통과시킨다.
    """
    taxonomy = load_taxonomy()
    allowed_categories = set(taxonomy_ids(taxonomy, "categories"))
    allowed_tags = set(taxonomy_ids(taxonomy, "scenario_tags"))

    category = LEGACY_CATEGORY_ALIASES.get(as_text(row.get("category")), row.get("category"))
    row["category"] = category if category in allowed_categories else "other_known_scam"

    article_type = LEGACY_ARTICLE_TYPE_ALIASES.get(
        as_text(row.get("article_type")), row.get("article_type")
    )
    row["article_type"] = article_type if article_type in ALLOWED_ARTICLE_TYPES else "기타"

    for field in ARRAY_FIELDS:
        values = as_list(row.get(field))
        if field == "scenario_tags" and allowed_tags:
            values = [value for value in values if value in allowed_tags]
        row[field] = values

    for field in BOOLEAN_FIELDS:
        row[field] = as_bool(row.get(field))
    if row["category"] == "novel_scam":
        row["is_novel"] = True

    try:
        row["category_confidence"] = min(1.0, max(0.0, float(row.get("category_confidence", 0))))
    except (TypeError, ValueError):
        row["category_confidence"] = 0.0

    try:
        row["severity_score"] = min(3, max(1, int(row.get("severity_score", 1))))
    except (TypeError, ValueError):
        row["severity_score"] = 1

    row["taxonomy_version"] = row.get("taxonomy_version") or taxonomy.get(
        "taxonomy_version", DEFAULT_TAXONOMY_VERSION
    )
    row["schema_version"] = int(
        row.get("schema_version") or taxonomy.get("schema_version", CURRENT_SCHEMA_VERSION)
    )
    if source_kind:
        row["source_kind"] = source_kind
    return row


def normalize_official(row: dict[str, Any]) -> dict[str, Any]:
    return normalize_structured({**OFFICIAL_DEFAULTS, **row}, source_kind="official_scenario")


def structure_article(article: dict[str, Any], verbose: bool = False) -> dict[str, Any]:
    """raw 기사 한 건 → 구조화 행. LLM 호출 1회."""
    body = {
        "model": UPSTAGE_STRUCTURING_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You extract Korean fraud data into strict JSON. Return JSON only.",
            },
            {"role": "user", "content": build_structuring_prompt(article)},
        ],
        "temperature": 0,
        "stream": False,
    }
    payload = http_json(UPSTAGE_CHAT_URL, body, upstage_key(), timeout=60, verbose=verbose)
    structured = normalize_structured(
        extract_json_object(payload["choices"][0]["message"]["content"])
    )
    # filled_by="pipeline" 필드는 여기서 채운다. headline_ko는 모델이 값을 흘려보내도
    # 원문 제목으로 덮어써, 원문을 권위 있는 소스로 유지한다.
    structured.update(
        {
            "headline_ko": clean_text(article.get("title")),
            "raw_article_id": article["id"],
            "article_published_at": article.get("published_at"),
            "article_url": article["link"],
            "source": article["source"],
            "source_kind": article.get("source_kind") or source_kind_for(article["source"]),
            "publisher": article.get("publisher"),
            "google_news_url": (
                article.get("rss_link") if article.get("rss_link") != article["link"] else None
            ),
            "structured_at": now_iso(),
            "llm_model": UPSTAGE_STRUCTURING_MODEL,
        }
    )
    return structured


def structure(limit: int | None = None, verbose: bool = False) -> dict[str, Any]:
    """아직 구조화하지 않은 raw 기사를 처리한다.

    처리 완료 판정은 structured_scam_articles.jsonl에 실제로 쓰였는지로 한다.
    실패하면 append_jsonl에 도달하지 못하므로 다음 실행에서 자동으로 다시 대기열에 오른다.
    """
    raw_rows = read_jsonl(RAW_JSONL)
    done_ids = {row.get("raw_article_id") for row in read_jsonl(STRUCTURED_JSONL)}
    pending = [row for row in raw_rows if row.get("id") not in done_ids]
    if limit is not None:
        pending = pending[:limit]

    structured_count = 0
    irrelevant_count = 0
    failed: list[dict[str, str]] = []

    for index, article in enumerate(pending, start=1):
        if verbose:
            print(f"[structure] {index}/{len(pending)} {article['title'][:70]}", flush=True)
        try:
            row = structure_article(article, verbose=verbose)
            append_jsonl(STRUCTURED_JSONL, [row])
        except Exception as exc:
            failed.append({"id": article.get("id", ""), "error": str(exc)})
            print(f"[structure] 실패 {article.get('id')}: {exc}", file=sys.stderr, flush=True)
            continue

        if row["category"] == "irrelevant":
            irrelevant_count += 1
        else:
            structured_count += 1

    return {
        "pending": len(pending),
        "structured": structured_count,
        "stored_irrelevant": irrelevant_count,
        "failed": failed,
        "path": str(STRUCTURED_JSONL),
    }


# ---------------------------------------------------------------------------
# 3. 색인 (임베딩 텍스트 / 페이로드 / Qdrant 업로드)
# ---------------------------------------------------------------------------


def date_parts(value: Any) -> dict[str, Any]:
    """filled_by="derived" 필드를 계산한다."""
    text = as_text(value)
    if not text:
        return {}
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return {"article_published_date": text[:10] if len(text) >= 10 else text}
    return {
        "article_published_date": parsed.date().isoformat(),
        "article_published_year": parsed.year,
        "article_published_month": parsed.month,
    }


def retrieval_text(row: dict[str, Any]) -> str:
    """사용자 상황과 대조할 텍스트. RETRIEVAL_FIELDS의 근거는 위 정의부 참고."""
    return "\n".join(text for key in RETRIEVAL_FIELDS if (text := as_text(row.get(key))))


def is_indexable(row: dict[str, Any], min_confidence: float = 0.0) -> bool:
    if row.get("category") == "irrelevant":
        return False
    if float(row.get("category_confidence", 0)) < min_confidence:
        return False
    if len(retrieval_text(row)) < MIN_RETRIEVAL_TEXT_CHARS:
        return False
    return any(as_text(row.get(key)) for key in ("headline_ko", "summary_ko", "modus_operandi_ko"))


def build_embedding_text(row: dict[str, Any]) -> str:
    """벡터로 만들 텍스트. VECTOR_TEXT_FIELDS(=SCHEMA의 vector_label)에서 나온다."""
    return "\n".join(
        f"{label}: {text}"
        for label, key in VECTOR_TEXT_FIELDS
        if (text := as_text(row.get(key)))
    )


def use_cases(row: dict[str, Any]) -> list[str]:
    """이 사례를 어떤 화면·기능에서 쓸 수 있는지. 검색 시 query_filter로 좁히는 데 쓴다."""
    cases = ["chat_similar_case"]
    if row.get("source_kind") == "official_scenario":
        cases.append("official_case_reference")
    if as_bool(row.get("is_novel")):
        cases.append("novel_scam_tab")
    if as_bool(row.get("is_youth_targeted")):
        cases.append("youth_targeted_filter")
    if as_text(row.get("warning_signs")):
        cases.append("learning_content")
    return cases


def point_id(row: dict[str, Any]) -> str:
    """Qdrant point id. raw_article_id 기준이라 재구조화해도 같은 id가 나온다.
    그래서 내용을 갱신하려면 embed --force 가 필요하다."""
    source_id = as_text(row.get("raw_article_id")) or as_text(row.get("article_url"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, source_id))


def build_payload(row: dict[str, Any], vector_text: str) -> dict[str, Any]:
    """Qdrant 페이로드. 최상위 평면 필드 + filter_metadata + display_metadata 3층."""
    normalized = dict(row)
    normalized.update(date_parts(row.get("article_published_at")))

    payload: dict[str, Any] = {
        "vector_text": vector_text,
        "vector_text_fields": [key for _, key in VECTOR_TEXT_FIELDS],
        "embedding_model": UPSTAGE_EMBEDDING_MODEL,
        "use_cases": use_cases(normalized),
    }
    for key in PAYLOAD_TOP_LEVEL_FIELDS:
        if key in normalized:
            payload[key] = normalized[key]

    payload["filter_metadata"] = {
        key: normalized[key]
        for key in FILTER_METADATA_FIELDS
        if normalized.get(key) not in (None, "", [])
    }
    payload["display_metadata"] = {
        key: normalized[key]
        for key in DISPLAY_METADATA_FIELDS
        if normalized.get(key) not in (None, "", [])
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def load_index_rows(min_confidence: float = 0.0, skip_official: bool = False) -> list[dict[str, Any]]:
    """공식 시나리오 + 뉴스 구조화 자료를 합쳐 색인 대상만 남긴다.

    skip_official=True면 공식 시나리오를 뺀다. 손으로 정리한 자료라 재구조화 대상이
    아니고 내용이 바뀌지 않으므로, 뉴스 쪽만 다시 올릴 때 헛일을 줄일 수 있다.
    (VECTOR_TEXT_ORDER를 바꾸지 않는 한 공식 시나리오의 벡터는 그대로 유효하다.)
    """
    rows = [] if skip_official else [
        normalize_official(row) for row in read_jsonl(OFFICIAL_SCENARIOS_JSONL)
    ]
    rows.extend(normalize_structured(row) for row in read_jsonl(STRUCTURED_JSONL))

    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        if is_indexable(row, min_confidence):
            unique[point_id(row)] = row
    return list(unique.values())


def embed_texts(texts: list[str]) -> list[list[float]]:
    payload = http_json(
        UPSTAGE_EMBEDDING_URL,
        {"model": UPSTAGE_EMBEDDING_MODEL, "input": texts},
        upstage_key(),
        timeout=90,
    )
    vectors = [item["embedding"] for item in sorted(payload["data"], key=lambda x: x["index"])]
    for vector in vectors:
        if len(vector) != QDRANT_VECTOR_SIZE:
            raise RuntimeError(
                f"임베딩 차원이 {len(vector)}입니다. QDRANT_VECTOR_SIZE={QDRANT_VECTOR_SIZE} "
                f"또는 UPSTAGE_EMBEDDING_MODEL={UPSTAGE_EMBEDDING_MODEL} 설정을 확인하세요."
            )
    return vectors


def embed_and_store(
    batch_size: int = 16,
    min_confidence: float = 0.0,
    force: bool = False,
    verbose: bool = False,
    skip_official: bool = False,
) -> dict[str, Any]:
    """색인 대상을 임베딩해 Qdrant에 올린다.

    force=False면 이미 올라간 point는 건너뛴다. 구조화 내용을 고친 뒤에는
    point_id가 그대로라 건너뛰게 되므로, 반드시 force=True로 돌려야 반영된다.
    """
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ImportError as exc:
        raise RuntimeError("qdrant-client가 필요합니다. pip install -r requirements.txt") from exc

    api_key = get_secret("QDRANT_API_KEY")
    if not api_key:
        raise RuntimeError("QDRANT_API_KEY 가 필요합니다. (Streamlit Secrets 또는 환경변수)")

    rows = load_index_rows(min_confidence, skip_official=skip_official)
    targets = [(point_id(row), row) for row in rows]

    client = QdrantClient(url=QDRANT_URL, api_key=api_key)
    if not client.collection_exists(QDRANT_COLLECTION):
        client.create_collection(
            collection_name=QDRANT_COLLECTION,
            vectors_config=VectorParams(size=QDRANT_VECTOR_SIZE, distance=Distance.COSINE),
        )

    if not force and targets:
        existing = {
            str(point.id)
            for point in client.retrieve(
                collection_name=QDRANT_COLLECTION,
                ids=[row_id for row_id, _ in targets],
                with_payload=False,
                with_vectors=False,
            )
        }
        targets = [(row_id, row) for row_id, row in targets if row_id not in existing]

    upserted = 0
    for start in range(0, len(targets), batch_size):
        batch = targets[start : start + batch_size]
        texts = [build_embedding_text(row) for _, row in batch]
        vectors = embed_texts(texts)
        client.upsert(
            collection_name=QDRANT_COLLECTION,
            points=[
                PointStruct(id=row_id, vector=vector, payload=build_payload(row, text))
                for (row_id, row), vector, text in zip(batch, vectors, texts, strict=True)
            ],
        )
        upserted += len(batch)
        if verbose:
            print(f"[embed] {upserted}/{len(targets)} upserted", flush=True)

    return {
        "collection": QDRANT_COLLECTION,
        "embedding_model": UPSTAGE_EMBEDDING_MODEL,
        "official_rows": 0 if skip_official else len(read_jsonl(OFFICIAL_SCENARIOS_JSONL)),
        "structured_rows": len(read_jsonl(STRUCTURED_JSONL)),
        "indexable_rows": len(rows),
        "upserted": upserted,
        "skipped_existing": len(rows) - len(targets),
    }


# ---------------------------------------------------------------------------
# 4. 일회성 보정 명령
#
# 정기 실행에는 들어가지 않는다. 과거 데이터의 결함을 소급해 고치는 용도다.
# 모두 여러 번 돌려도 결과가 같다.
# ---------------------------------------------------------------------------


def backfill_bodies(
    limit: int | None = None, timeout: int = 12, verbose: bool = False
) -> dict[str, Any]:
    """이미 수집된 raw 기사에 body_text를 채운다.

    본문 수집을 붙이기 전에 모은 기사는 summary_snippet이 제목 한 줄뿐이라
    구조화가 값을 지어내는 원인이 됐다. 이미 채워진 행은 건너뛴다.
    """
    rows = read_jsonl(RAW_JSONL)
    pending = [
        row for row in rows
        if not as_text(row.get("body_text")) and (row.get("link") or "").startswith("http")
    ]
    if limit is not None:
        pending = pending[:limit]

    filled = 0
    for index, row in enumerate(pending, start=1):
        body = fetch_article_body(row["link"], timeout=timeout)
        if body:
            row["body_text"] = body
            filled += 1
        if verbose:
            print(f"[backfill] {index}/{len(pending)} "
                  f"{f'{len(body)}자' if body else '실패'} {row['title'][:52]}", flush=True)

    if filled:
        write_jsonl(RAW_JSONL, rows)

    return {
        "rows": len(rows),
        "attempted": len(pending),
        "filled": filled,
        "failed": len(pending) - filled,
        "with_body_total": sum(1 for row in rows if as_text(row.get("body_text"))),
        "path": str(RAW_JSONL),
    }


def restructure(limit: int | None = None, verbose: bool = False) -> dict[str, Any]:
    """본문(body_text)이 생긴 기사만 다시 구조화한다.

    전량이 아니라 일부인 이유: 본문 없이 제목만으로 재구조화하면 결과가 나아지지 않고
    API 호출만 쓴다. 본문이 있는 기사만 새로 만들고 나머지는 기존 행을 유지한다.

    작업 중에는 임시 파일에 쓰고 끝난 뒤 원본과 교체한다. 그래야 실행 도중에도
    앱(scam_feed)이 읽는 파일이 비지 않는다. 중단되면 임시 파일이 남아 이어서 진행한다.

    끝난 뒤에는 반드시 `embed --force`를 돌려야 Qdrant에 반영된다(point_id가 같아서).
    """
    progress_path = STRUCTURED_JSONL.with_suffix(".restructure.jsonl")
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    backup_path = BACKUP_DIR / f"{STRUCTURED_JSONL.stem}.{stamp}.jsonl"

    raw_by_id = {row["id"]: row for row in read_jsonl(RAW_JSONL) if row.get("id")}
    existing = {row.get("raw_article_id"): row for row in read_jsonl(STRUCTURED_JSONL)}
    already = {row.get("raw_article_id") for row in read_jsonl(progress_path)}

    pending = [
        article_id
        for article_id, row in raw_by_id.items()
        if as_text(row.get("body_text")) and article_id not in already
    ]
    if limit is not None:
        pending = pending[:limit]

    rebuilt = 0
    failed: list[dict[str, str]] = []
    for index, article_id in enumerate(pending, start=1):
        if verbose:
            print(f"[restructure] {index}/{len(pending)} "
                  f"{raw_by_id[article_id]['title'][:60]}", flush=True)
        try:
            append_jsonl(progress_path, [structure_article(raw_by_id[article_id], verbose=verbose)])
            rebuilt += 1
        except Exception as exc:
            failed.append({"id": article_id, "error": str(exc)})
            print(f"[restructure] 실패 {article_id}: {exc}", file=sys.stderr, flush=True)

    # 남은 대상이 없을 때만 교체한다. 중간에 끊기면 진행분이 임시 파일에 남는다.
    done_now = {row.get("raw_article_id") for row in read_jsonl(progress_path)}
    failed_ids = {item["id"] for item in failed}
    remaining = [
        article_id
        for article_id, row in raw_by_id.items()
        if as_text(row.get("body_text")) and article_id not in done_now and article_id not in failed_ids
    ]

    swapped = False
    if not remaining:
        merged = dict(existing)
        for row in read_jsonl(progress_path):
            merged[row.get("raw_article_id")] = row  # 새로 만든 것으로 덮어씀
        write_jsonl(backup_path, list(existing.values()))
        write_jsonl(STRUCTURED_JSONL, list(merged.values()))
        progress_path.unlink(missing_ok=True)
        swapped = True

    return {
        "rebuilt_this_run": rebuilt,
        "failed": failed,
        "remaining": len(remaining),
        "swapped": swapped,
        "backup": str(backup_path) if swapped else None,
        "next_step": (
            "python scam_data_pipeline.py embed --force" if swapped else "재실행해 나머지를 마저 처리"
        ),
    }


def repair_headlines(dry_run: bool = False, verbose: bool = False) -> dict[str, Any]:
    """structured의 headline_ko를 원문 제목으로 다시 맞춘다.

    예전 파이프라인은 headline_ko를 LLM에게 생성시켰고, 원문이 멀쩡한데도 제목이 깨진
    행이 남았다. 지금은 structure_article()이 원문을 복사하므로, 이 명령은 같은 규칙을
    과거 데이터에 소급 적용하는 backfill이다.
    """
    titles = {
        row["id"]: clean_text(row.get("title")) for row in read_jsonl(RAW_JSONL) if row.get("id")
    }
    rows = read_jsonl(STRUCTURED_JSONL)

    repaired = 0
    unmatched = 0
    for row in rows:
        title = titles.get(row.get("raw_article_id"))
        if not title:
            unmatched += 1
            continue
        if row.get("headline_ko") != title:
            if verbose:
                print(f"[repair] {row.get('headline_ko')!r}\n     ->  {title!r}", flush=True)
            row["headline_ko"] = title
            repaired += 1

    if repaired and not dry_run:
        write_jsonl(STRUCTURED_JSONL, rows)

    return {
        "rows": len(rows),
        "repaired": repaired,
        "unmatched_raw_article_id": unmatched,
        "garbled_headline_after": sum(1 for row in rows if looks_garbled(row.get("headline_ko"))),
        "garbled_summary_ko": sum(1 for row in rows if looks_garbled(row.get("summary_ko"))),
        "dry_run": dry_run,
        "path": str(STRUCTURED_JSONL),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

REGULAR_COMMANDS = ("collect", "structure", "embed", "run")
REPAIR_COMMANDS = ("backfill-bodies", "restructure", "repair-headlines")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="사기 사례 RAG 데이터 파이프라인")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in (*REGULAR_COMMANDS, *REPAIR_COMMANDS):
        sub = subparsers.add_parser(name)
        sub.add_argument("--verbose", action="store_true")

        if name in ("collect", "run"):
            sub.add_argument("--limit", type=int, default=20, help="피드당 신규 수집 상한")
            sub.add_argument("--timeout", type=int, default=8)
            sub.add_argument("--no-resolve-urls", action="store_true", help="원문 URL 복원 생략")
            sub.add_argument("--no-fetch-bodies", action="store_true", help="원문 본문 수집 생략")
        if name in ("structure", "run"):
            sub.add_argument("--structure-limit", type=int, default=None, help="LLM 구조화 호출 상한")
        if name in ("embed", "run"):
            sub.add_argument("--batch-size", type=int, default=16)
            sub.add_argument("--min-confidence", type=float, default=0.0)
            sub.add_argument("--force", action="store_true", help="이미 저장된 항목도 재임베딩")
            sub.add_argument("--skip-official", action="store_true",
                             help="공식 시나리오는 건너뛰기 (내용이 안 바뀌므로 재임베딩 불필요)")
        if name == "backfill-bodies":
            sub.add_argument("--limit", type=int, default=None, help="이번에 받아올 기사 수 상한")
            sub.add_argument("--timeout", type=int, default=12)
        if name == "restructure":
            sub.add_argument("--limit", type=int, default=None, help="이번 회차 재구조화 상한")
        if name == "repair-headlines":
            sub.add_argument("--dry-run", action="store_true", help="고치지 않고 결과만 확인")

    return parser


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "backfill-bodies":
        return {"backfill_bodies": backfill_bodies(
            limit=args.limit, timeout=args.timeout, verbose=args.verbose
        )}
    if args.command == "restructure":
        return {"restructure": restructure(limit=args.limit, verbose=args.verbose)}
    if args.command == "repair-headlines":
        return {"repair_headlines": repair_headlines(dry_run=args.dry_run, verbose=args.verbose)}

    result: dict[str, Any] = {}
    if args.command in ("collect", "run"):
        result["collect"] = collect(
            limit=args.limit,
            timeout=args.timeout,
            verbose=args.verbose,
            resolve_urls=not args.no_resolve_urls,
            fetch_bodies=not args.no_fetch_bodies,
        )
    if args.command in ("structure", "run"):
        result["structure"] = structure(limit=args.structure_limit, verbose=args.verbose)
    if args.command in ("embed", "run"):
        result["embed"] = embed_and_store(
            batch_size=args.batch_size,
            min_confidence=args.min_confidence,
            force=args.force,
            verbose=args.verbose,
            skip_official=args.skip_official,
        )
    return result


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = dispatch(args)
    except RuntimeError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
