"""사기 사례 RAG 데이터 파이프라인.

운영 흐름:
1. 공식 자료는 사람이 구조화해서 data/official_scenarios.jsonl에 저장한다.
2. 신규 자료는 Google News 키워드 검색 RSS와 공식기관 RSS(KISA 보호나라 보안공지,
   KISA 보호나라 신고/대응 안내, 금융위원회 보도자료)로 수집한다.
3. 신규 자료는 data/taxonomy/scam_taxonomy.json의 category/scenario_tags 기준으로 구조화한다.
4. 공식 자료 + 신규 구조화 자료를 같은 스키마로 정규화해 임베딩하고 Qdrant에 업로드한다.

실행:
    python scam_data_pipeline.py collect --limit 20
    python scam_data_pipeline.py structure
    python scam_data_pipeline.py embed
    python scam_data_pipeline.py run --verbose
"""

from __future__ import annotations

import argparse
import email.utils
import hashlib
import html
import json
import os
import re
import ssl
import sys
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


# ---------------------------------------------------------------------------
# API 설정
# ---------------------------------------------------------------------------


UPSTAGE_CHAT_URL = "https://api.upstage.ai/v1/chat/completions"
UPSTAGE_STRUCTURING_MODEL = os.getenv("UPSTAGE_STRUCTURING_MODEL", "solar-mini")
UPSTAGE_EMBEDDING_URL = "https://api.upstage.ai/v1/embeddings"
UPSTAGE_EMBEDDING_MODEL = os.getenv("UPSTAGE_EMBEDDING_MODEL", "embedding-passage")

QDRANT_URL = os.getenv(
    "QDRANT_URL",
    "https://32cd9c82-9cec-491c-acc9-fbd57c385e1b.sa-east-1-0.aws.cloud.qdrant.io",
)
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "0818")
QDRANT_VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "4096"))


# ---------------------------------------------------------------------------
# 스키마: 공식 자료 입력 / 신규 자료 출력
# ---------------------------------------------------------------------------


OFFICIAL_INPUT_FIELDS = [
    "raw_article_id",
    "article_published_at",
    "article_url",
    "headline_ko",
    "summary_ko",
    "article_type",
    "category",
    "scenario_tags",
    "modus_operandi_ko",
    "approach_channel",
    "impersonation_target",
    "lure_hook",
    "victim_action_requested",
    "payment_method",
    "target_demographic",
    "is_youth_targeted",
    "warning_signs",
    "severity_score",
]

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

NEWS_LLM_FIELDS = [
    "headline_ko",
    "summary_ko",
    "article_type",
    "category",
    "scenario_tags",
    "is_novel",
    "novelty_evidence",
    "modus_operandi_ko",
    "approach_channel",
    "impersonation_target",
    "lure_hook",
    "victim_action_requested",
    "payment_method",
    "target_demographic",
    "is_youth_targeted",
    "warning_signs",
    "severity_score",
    "category_confidence",
]

ARRAY_FIELDS = {
    "scenario_tags",
    "approach_channel",
    "impersonation_target",
    "victim_action_requested",
    "payment_method",
    "target_demographic",
    "warning_signs",
}

BOOLEAN_FIELDS = {"is_novel", "is_youth_targeted"}
ALLOWED_ARTICLE_TYPES = {"사례", "신종경보", "기타"}

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


# ---------------------------------------------------------------------------
# 벡터 데이터 / 메타데이터 구분
# ---------------------------------------------------------------------------


VECTOR_TEXT_FIELDS = [
    ("제목", "headline_ko"),
    ("요약", "summary_ko"),
    ("카테고리", "category"),
    ("시나리오태그", "scenario_tags"),
    ("수법", "modus_operandi_ko"),
    ("접근경로", "approach_channel"),
    ("사칭대상", "impersonation_target"),
    ("유인책", "lure_hook"),
    ("요구행동", "victim_action_requested"),
    ("결제수단", "payment_method"),
    ("대상층", "target_demographic"),
    ("위험신호", "warning_signs"),
]

PAYLOAD_TOP_LEVEL_FIELDS = [
    "raw_article_id",
    "article_url",
    "article_published_at",
    "article_published_date",
    "article_published_year",
    "article_published_month",
    "headline_ko",
    "summary_ko",
    "article_type",
    "category",
    "scenario_tags",
    "is_novel",
    "is_youth_targeted",
    "severity_score",
    "category_confidence",
    "source",
    "source_kind",
    "publisher",
    "taxonomy_version",
    "schema_version",
]

FILTER_METADATA_FIELDS = [
    "category",
    "scenario_tags",
    "article_type",
    "is_novel",
    "is_youth_targeted",
    "severity_score",
    "category_confidence",
    "approach_channel",
    "impersonation_target",
    "victim_action_requested",
    "payment_method",
    "target_demographic",
    "source",
    "source_kind",
    "publisher",
    "article_published_at",
    "structured_at",
    "taxonomy_version",
    "schema_version",
]

DISPLAY_METADATA_FIELDS = [
    "headline_ko",
    "summary_ko",
    "novelty_evidence",
    "modus_operandi_ko",
    "lure_hook",
    "warning_signs",
    "target_demographic",
    "raw_article_id",
    "article_url",
    "google_news_url",
    "source",
    "source_kind",
    "publisher",
]


# ---------------------------------------------------------------------------
# 신규 자료 수집 설정
#
# Google News는 검색어 기반이라 노이즈가 많으므로 1차 키워드 필터를 적용한다.
# KISA/금융위 RSS는 공식 출처라 게시물을 모두 raw에 저장하고, structure 단계에서
# taxonomy 기준으로 사례/신종경보/기타/irrelevant를 판단한다.
# ---------------------------------------------------------------------------


MAX_SNIPPET_CHARS = 1200
FEED_UA = "JikimiDataCollector/0.2 (+https://local)"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

GOOGLE_NEWS_QUERY_TERMS = [
    "신종 사기",
    "신종 피싱",
    "청년 사기",
]

GOOGLE_NEWS_QUERY_LIMITS = {
    "신종 사기": 50,
    "신종 피싱": 50,
    "청년 사기": 50,
}

RSS_FEEDS = [
    {
        "source": "kisa_boho_security_notice",
        "url": "https://www.boho.or.kr/kr/rss.do?bbsId=B0000133",
    },
    {
        "source": "kisa_boho_report_guide",
        "url": "https://www.boho.or.kr/kr/rss.do?bbsId=B0000127",
    },
    {
        "source": "fsc_press_release",
        "url": "http://www.fsc.go.kr/about/fsc_bbs_rss/?fid=0111",
    },
]

FRAUD_TERMS_STRONG = {
    "금융사기",
    "보이스피싱",
    "스미싱",
    "메신저피싱",
    "몸캠피싱",
    "큐싱",
    "로맨스스캠",
    "로맨스 스캠",
    "투자리딩방",
    "리딩방 사기",
    "투자사기",
    "투자 사기",
    "코인사기",
    "가상자산 사기",
    "중고거래 사기",
    "노쇼사기",
    "대출사기",
    "대출 빙자",
    "대포통장",
    "통장 대여",
    "악성앱",
    "악성 앱",
    "신종 사기",
    "신종 피싱",
    "청년 사기",
    "사칭 사기",
    "사칭 피싱",
}

FRAUD_TERMS_WEAK = {
    "사기",
    "피싱",
    "스캠",
    "사칭",
    "명의도용",
    "사기범",
    "사기단",
}

MODUS_TERMS = {
    "미끼",
    "속여",
    "속아",
    "속인",
    "유인",
    "유도",
    "편취",
    "갈취",
    "수법",
    "피해자",
    "피해액",
    "주의",
    "예방",
    "신고",
    "급증",
    "기승",
    "확산",
    "신종",
    "변종",
    "조심",
    "설치",
    "송금",
    "이체",
    "가짜",
    "허위",
    "요구",
    "협박",
}

EXCLUDE_TERMS = {
    "사기 진작",
    "사기진작",
    "구속",
    "송치",
    "기소",
    "징역",
    "선고",
    "영장",
    "압수수색",
    "검거",
    "피소",
    "고발",
    "재판",
    "항소",
    "실형",
    "무죄",
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


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for row in rows:
            row = strip_surrogate_chars(row)
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def http_json(url: str, body: dict[str, Any], api_key: str, timeout: int) -> dict[str, Any]:
    body = strip_surrogate_chars(body)
    request = urllib.request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout, context=ssl_context()) as response:
        return json.loads(response.read().decode("utf-8"))


def upstage_key() -> str:
    api_key = os.getenv("UPSTAGE_API") or os.getenv("UPSTAGE_API_KEY")
    if not api_key:
        raise RuntimeError("UPSTAGE_API 또는 UPSTAGE_API_KEY가 필요합니다.")
    return api_key


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
# 1. 신규 자료 수집
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
        encoded = urllib.parse.urlencode(
            {"q": keyword, "hl": "ko", "gl": "KR", "ceid": "KR:ko"}
        )
        feeds.append(
            {
                "source": f"google_news:{keyword}",
                "url": f"https://news.google.com/rss/search?{encoded}",
                "limit": GOOGLE_NEWS_QUERY_LIMITS.get(keyword),
            }
        )
    return feeds


def resolve_google_news_url(link: str, timeout: int = 15) -> str:
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
            should_filter = article.source_kind == "news"
            if article.content_hash in seen:
                continue
            if should_filter and not coarse_is_fraud_related(article):
                continue
            seen.add(article.content_hash)
            if resolve_urls:
                article.link = resolve_google_news_url(article.link, timeout=timeout + 7)
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
        "path": str(RAW_JSONL),
        "per_feed": per_feed,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# 2. 신규 자료 구조화
# ---------------------------------------------------------------------------


def build_structuring_prompt(article: dict[str, Any]) -> str:
    taxonomy = load_taxonomy()
    category_ids = taxonomy_ids(taxonomy, "categories")
    scenario_tag_ids = taxonomy_ids(taxonomy, "scenario_tags")
    return f"""
너는 금융사기 사례 RAG를 위한 신규 자료 구조화 분류기다.
아래 수집 자료를 읽고 JSON 객체 하나만 출력해라. 설명 문장이나 markdown은 금지한다.

category 기준:
{format_taxonomy_items(taxonomy.get("categories", []))}

scenario_tags 기준:
{format_taxonomy_items(taxonomy.get("scenario_tags", []))}

필드:
{", ".join(NEWS_LLM_FIELDS)}

규칙:
- category는 반드시 다음 중 하나만 선택한다: {", ".join(category_ids)}
- scenario_tags는 반드시 다음 중 0개 이상만 선택한다: {", ".join(scenario_tag_ids) if scenario_tag_ids else "등록된 태그 없음"}
- 같은 의미의 scenario tag를 새로 만들지 않는다.
- 기존 category/scenario_tags로 설명 가능하면 is_novel=false.
- 기존 기준으로 설명하기 어려운 신규·변종 수법이면 category=novel_scam, is_novel=true.
- 사기는 맞지만 기존 8개 category에 딱 맞지 않는 알려진 유형이면 category=other_known_scam.
- 사기 사례로 쓰기 어렵다면 category=irrelevant.
- article_type은 사례, 신종경보, 기타 중 하나만 쓴다.
- is_youth_targeted는 20대·30대·청년·대학생·취준생·사회초년생이 명시되었거나,
  청년층에게 특히 노출 가능성이 높은 온라인/SNS/투자/부업/중고거래/대출 수법이면 true.
- 배열 필드는 배열로, 모르는 문자열 필드는 "없음", 모르는 배열 필드는 []로 채운다.
- category_confidence는 0~1, severity_score는 1~3 정수로 출력한다.

수집 자료:
제목: {article["title"]}
요약: {article["summary_snippet"]}
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
    taxonomy = load_taxonomy()
    allowed_categories = set(taxonomy_ids(taxonomy, "categories"))
    allowed_tags = set(taxonomy_ids(taxonomy, "scenario_tags"))

    category = LEGACY_CATEGORY_ALIASES.get(as_text(row.get("category")), row.get("category"))
    row["category"] = category if category in allowed_categories else "other_known_scam"

    article_type = LEGACY_ARTICLE_TYPE_ALIASES.get(as_text(row.get("article_type")), row.get("article_type"))
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
    row["schema_version"] = int(row.get("schema_version") or taxonomy.get("schema_version", CURRENT_SCHEMA_VERSION))
    if source_kind:
        row["source_kind"] = source_kind
    return row


def normalize_official(row: dict[str, Any]) -> dict[str, Any]:
    merged = {**OFFICIAL_DEFAULTS, **row}
    return normalize_structured(merged, source_kind="official_scenario")


def structure_article(article: dict[str, Any]) -> dict[str, Any]:
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
    payload = http_json(UPSTAGE_CHAT_URL, body, upstage_key(), timeout=60)
    structured = normalize_structured(extract_json_object(payload["choices"][0]["message"]["content"]))
    structured.update(
        {
            "raw_article_id": article["id"],
            "article_published_at": article.get("published_at"),
            "article_url": article["link"],
            "source": article["source"],
            "source_kind": article.get("source_kind") or source_kind_for(article["source"]),
            "publisher": article.get("publisher"),
            "google_news_url": article.get("rss_link") if article.get("rss_link") != article["link"] else None,
            "structured_at": now_iso(),
            "llm_model": UPSTAGE_STRUCTURING_MODEL,
        }
    )
    return structured


def structure(limit: int | None = None, verbose: bool = False) -> dict[str, Any]:
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
            row = structure_article(article)
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
# 3. 임베딩 텍스트 / 메타데이터 생성
# ---------------------------------------------------------------------------


def date_parts(value: Any) -> dict[str, Any]:
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


def is_indexable(row: dict[str, Any], min_confidence: float = 0.0) -> bool:
    if row.get("category") == "irrelevant":
        return False
    if float(row.get("category_confidence", 0)) < min_confidence:
        return False
    return any(as_text(row.get(key)) for key in ("headline_ko", "summary_ko", "modus_operandi_ko"))


def build_embedding_text(row: dict[str, Any]) -> str:
    return "\n".join(
        f"{label}: {text}"
        for label, key in VECTOR_TEXT_FIELDS
        if (text := as_text(row.get(key)))
    )


def use_cases(row: dict[str, Any]) -> list[str]:
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
    source_id = as_text(row.get("raw_article_id")) or as_text(row.get("article_url"))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, source_id))


def build_payload(row: dict[str, Any], vector_text: str) -> dict[str, Any]:
    normalized = dict(row)
    normalized.update(date_parts(row.get("article_published_at")))

    payload = {
        "vector_text": vector_text,
        "vector_text_fields": [key for _, key in VECTOR_TEXT_FIELDS],
        "embedding_model": UPSTAGE_EMBEDDING_MODEL,
        "use_cases": use_cases(normalized),
    }
    for key in PAYLOAD_TOP_LEVEL_FIELDS:
        if key in normalized:
            payload[key] = normalized[key]

    payload["filter_metadata"] = {
        key: normalized[key] for key in FILTER_METADATA_FIELDS if normalized.get(key) not in (None, "", [])
    }
    payload["display_metadata"] = {
        key: normalized[key] for key in DISPLAY_METADATA_FIELDS if normalized.get(key) not in (None, "", [])
    }
    return {key: value for key, value in payload.items() if value not in (None, "", [])}


def load_index_rows(min_confidence: float = 0.0) -> list[dict[str, Any]]:
    rows = [normalize_official(row) for row in read_jsonl(OFFICIAL_SCENARIOS_JSONL)]
    rows.extend(normalize_structured(row) for row in read_jsonl(STRUCTURED_JSONL))

    unique: dict[str, dict[str, Any]] = {}
    for row in rows:
        if is_indexable(row, min_confidence):
            unique[point_id(row)] = row
    return list(unique.values())


# ---------------------------------------------------------------------------
# 4. 임베딩 + Qdrant 업로드
# ---------------------------------------------------------------------------


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
) -> dict[str, Any]:
    try:
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ImportError as exc:
        raise RuntimeError("qdrant-client가 필요합니다. pip install -r requirements.txt") from exc

    api_key = os.getenv("QDRANT_API_KEY")
    if not api_key:
        raise RuntimeError("QDRANT_API_KEY 환경변수가 필요합니다.")

    rows = load_index_rows(min_confidence)
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
        "official_rows": len(read_jsonl(OFFICIAL_SCENARIOS_JSONL)),
        "structured_rows": len(read_jsonl(STRUCTURED_JSONL)),
        "indexable_rows": len(rows),
        "upserted": upserted,
        "skipped_existing": len(rows) - len(targets),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="사기 사례 RAG 데이터 파이프라인")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("collect", "structure", "embed", "run"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--verbose", action="store_true")
        if name in ("collect", "run"):
            sub.add_argument("--limit", type=int, default=20, help="피드당 신규 수집 상한")
            sub.add_argument("--timeout", type=int, default=8)
            sub.add_argument("--no-resolve-urls", action="store_true", help="구글 뉴스 원문 URL 복원 생략")
        if name in ("structure", "run"):
            sub.add_argument("--structure-limit", type=int, default=None, help="LLM 구조화 호출 상한")
        if name in ("embed", "run"):
            sub.add_argument("--batch-size", type=int, default=16)
            sub.add_argument("--min-confidence", type=float, default=0.0)
            sub.add_argument("--force", action="store_true", help="이미 저장된 항목도 재임베딩")

    args = parser.parse_args()
    try:
        result = dispatch(args)
    except RuntimeError as exc:
        print(f"[중단] {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if args.command in ("collect", "run"):
        result["collect"] = collect(
            limit=args.limit,
            timeout=args.timeout,
            verbose=args.verbose,
            resolve_urls=not args.no_resolve_urls,
        )
    if args.command in ("structure", "run"):
        result["structure"] = structure(limit=args.structure_limit, verbose=args.verbose)
    if args.command in ("embed", "run"):
        result["embed"] = embed_and_store(
            batch_size=args.batch_size,
            min_confidence=args.min_confidence,
            force=args.force,
            verbose=args.verbose,
        )
    return result


if __name__ == "__main__":
    sys.exit(main())
