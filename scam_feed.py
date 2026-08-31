"""요즘 수법 탭용 실데이터 로더.

data/structured_scam_articles.jsonl(뉴스 구조화 자료)를 scam_data_pipeline의 정규화기로
통과시켜, 뉴스 페이지(pages_files/news.py)가 쓰는 두 가지를 만든다.

- count_by_category(): 최근 N일 카테고리별 뉴스 기사 수 (섹션 1 배지)
- novel_scam_pool(): is_youth_targeted=true AND is_novel=true 기사 중 품질 필터 통과분 최신순 전체 (섹션 2 카드)

카테고리 ID는 data/taxonomy/scam_taxonomy.json 기준이고, mock_data.FRAUD_TYPES의 id와
1:1로 일치한다(voice_phishing, loan_scam, smishing, messenger_impersonation,
romance_scam, investment_scam, secondhand_scam, part_time_scam).
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from scam_data_pipeline import STRUCTURED_JSONL, as_text, normalize_structured, read_jsonl

# 섹션 2(신종 감지) 필터
NOVEL_ARTICLE_TYPES = {"사례", "신종경보"}
NOVEL_MIN_CONFIDENCE = 0.7

# response_guide_ko가 비어 있는 기사에만 쓰는 기본 문구
_AVOID_GUIDE = (
    "출처가 불분명한 연락이 송금·개인정보·앱 설치를 요구하면 일단 멈추고, "
    "상대가 준 번호가 아니라 직접 검색한 공식 대표번호로 확인하세요."
)

# 파일 mtime 기준 메모이즈 — 파이프라인이 jsonl을 다시 쓰면 자동 갱신된다.
_CACHE: dict = {}


def _article_date(row: dict) -> date | None:
    raw = (row.get("article_published_at") or row.get("structured_at") or "")[:10]
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def load_news_articles() -> list[dict]:
    """뉴스 구조화 자료를 정규화(레거시 category/article_type 별칭 정리 포함)해 반환."""
    key = STRUCTURED_JSONL.stat().st_mtime_ns if STRUCTURED_JSONL.exists() else 0
    if _CACHE.get("key") != key:
        _CACHE["key"] = key
        _CACHE["rows"] = [normalize_structured(row) for row in read_jsonl(STRUCTURED_JSONL)]
    return _CACHE["rows"]


def within_recent_days(row: dict, *, days: int = 30, as_of: date | None = None) -> bool:
    """as_of(기준일)로부터 뒤로 days일 이내면 True. as_of 기본값은 오늘."""
    as_of = as_of or date.today()
    article_day = _article_date(row)
    return article_day is not None and as_of - timedelta(days=days) < article_day <= as_of


def count_by_category(
    rows: list[dict], *, days: int = 30, as_of: date | None = None
) -> dict[str, int]:
    """최근 days일 내 뉴스 기사 수를 category별로 집계 (irrelevant 제외)."""
    counts: dict[str, int] = {}
    for row in rows:
        if row.get("category") == "irrelevant":
            continue
        if within_recent_days(row, days=days, as_of=as_of):
            counts[row["category"]] = counts.get(row["category"], 0) + 1
    return counts


def _clean_headline(text: str | None) -> str:
    """헤드라인 뒤에 붙는 ' - 매체명' 꼬리표를 떼어낸다."""
    return re.sub(r"\s*[-–—]\s*[^-–—]{1,25}$", "", (text or "").strip()).strip()


def _headline_tokens(text: str | None) -> set[str]:
    """헤드라인 토큰을 앞 2글자로 줄인 집합. 한국어 조사·활용어미 차이를 흡수해
    같은 사건을 다룬 여러 매체 기사를 묶어내는 데 쓴다."""
    return {
        token[:2]
        for token in re.split(r"[^\w가-힣]+", _clean_headline(text))
        if len(token) >= 2
    }


def _is_near_duplicate(tokens: set[str], seen_tokens: list[set[str]]) -> bool:
    for other in seen_tokens:
        shared = len(tokens & other)
        smaller = min(len(tokens), len(other)) or 1
        if shared >= 3 and shared / smaller >= 0.5:
            return True
    return False


def _fmt_detected_date(row: dict) -> str:
    detected = _article_date(row)
    return f"{detected.year}.{detected.month:02d}.{detected.day:02d}" if detected else "확인 중"


def _to_new_scam_card(row: dict) -> dict:
    """구조화 행 → render_new_scam_card가 먹는 카드 dict.

    필드 소스: 제목=headline_ko(뉴스 헤드라인, 비면 modus_operandi_ko) /
    수법=modus_operandi_ko / 요약=summary_ko(헤드라인과 같으면 생략) /
    감지일=article_published_at / url=article_url /
    "이 말 나오면 의심하세요"=warning_signs / "이렇게 피해요"=response_guide_ko (비면 _AVOID_GUIDE).
    as_text로 "없음"·"[]" 같은 빈값 표기를 걸러낸다.
    """
    red_flags = [flag for sign in (row.get("warning_signs") or []) if (flag := as_text(sign))]
    if not red_flags:
        red_flags = [as_text(row.get("lure_hook")) or "출처가 불분명한 접근"]
    headline = _clean_headline(row.get("headline_ko"))
    method = as_text(row.get("modus_operandi_ko"))
    summary = _clean_headline(as_text(row.get("summary_ko")))
    # summary_ko가 헤드라인을 그대로 옮겨온 기사가 있어, 같은 문장이면 요약을 비운다.
    if summary and summary == headline:
        summary = ""
    return {
        "tag": "신종 감지",
        "title": headline or method or "신종 수법",
        "method": method,
        "summary": summary,
        "red_flags": red_flags,
        "how_to_avoid": as_text(row.get("response_guide_ko")) or _AVOID_GUIDE,
        "article_title": as_text(row.get("publisher")) or "관련 기사",
        "article_url": row.get("article_url") or row.get("google_news_url"),
        "date": _fmt_detected_date(row),
    }


def novel_scam_pool(
    rows: list[dict], *, days: int = 30, as_of: date | None = None
) -> list[dict]:
    """품질 필터 + 헤드라인 근사중복 제거를 거친 신종 수법 카드 전체 목록(감지일 최신순).

    필터: is_youth_targeted=true AND is_novel=true / category != irrelevant
          / article_type in {사례, 신종경보} / category_confidence >= 0.7 / 최근 days일.
    같은 사건을 다룬 여러 매체 기사는 가장 최신 1건만 남긴다.
    """
    candidates = [
        row
        for row in rows
        if row.get("is_youth_targeted")
        and row.get("is_novel")
        and row.get("category") != "irrelevant"
        and row.get("article_type") in NOVEL_ARTICLE_TYPES
        and float(row.get("category_confidence") or 0) >= NOVEL_MIN_CONFIDENCE
        and within_recent_days(row, days=days, as_of=as_of)
    ]
    candidates.sort(key=lambda row: row.get("article_published_at") or "", reverse=True)

    pool: list[dict] = []
    seen_tokens: list[set[str]] = []
    for row in candidates:
        tokens = _headline_tokens(row.get("headline_ko"))
        if _is_near_duplicate(tokens, seen_tokens):
            continue
        seen_tokens.append(tokens)
        pool.append(_to_new_scam_card(row))
    return pool
