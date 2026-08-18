"""요즘 수법 탭에서 쓰는 변동 데이터와 집계 함수.

나중에 DB가 붙으면 SCAM_REPORTS / NEW_SCAM_PATTERNS 대신 DB 조회 결과를
이 함수들 안에서 집계해 반환하면 된다.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta


SCAM_REPORTS = [
    {"date": "2026-08-18", "fraud_type_id": "voice_phishing", "count": 44},
    {"date": "2026-08-12", "fraud_type_id": "voice_phishing", "count": 51},
    {"date": "2026-07-25", "fraud_type_id": "voice_phishing", "count": 33},
    {"date": "2026-08-17", "fraud_type_id": "loan_scam", "count": 28},
    {"date": "2026-08-09", "fraud_type_id": "loan_scam", "count": 36},
    {"date": "2026-07-27", "fraud_type_id": "loan_scam", "count": 30},
    {"date": "2026-08-18", "fraud_type_id": "smishing", "count": 62},
    {"date": "2026-08-11", "fraud_type_id": "smishing", "count": 71},
    {"date": "2026-07-23", "fraud_type_id": "smishing", "count": 43},
    {"date": "2026-08-15", "fraud_type_id": "messenger_impersonation", "count": 31},
    {"date": "2026-08-04", "fraud_type_id": "messenger_impersonation", "count": 29},
    {"date": "2026-07-29", "fraud_type_id": "messenger_impersonation", "count": 23},
    {"date": "2026-08-14", "fraud_type_id": "romance_scam", "count": 21},
    {"date": "2026-08-03", "fraud_type_id": "romance_scam", "count": 25},
    {"date": "2026-07-26", "fraud_type_id": "romance_scam", "count": 15},
    {"date": "2026-08-17", "fraud_type_id": "investment_scam", "count": 47},
    {"date": "2026-08-07", "fraud_type_id": "investment_scam", "count": 58},
    {"date": "2026-07-24", "fraud_type_id": "investment_scam", "count": 37},
    {"date": "2026-08-16", "fraud_type_id": "secondhand_scam", "count": 43},
    {"date": "2026-08-08", "fraud_type_id": "secondhand_scam", "count": 45},
    {"date": "2026-07-28", "fraud_type_id": "secondhand_scam", "count": 31},
    {"date": "2026-08-13", "fraud_type_id": "part_time_scam", "count": 24},
    {"date": "2026-08-05", "fraud_type_id": "part_time_scam", "count": 27},
    {"date": "2026-07-30", "fraud_type_id": "part_time_scam", "count": 21},
    {"date": "2026-08-13", "fraud_type_id": "concert_ticket_takeover", "count": 10},
    {"date": "2026-08-06", "fraud_type_id": "concert_ticket_takeover", "count": 8},
    {"date": "2026-08-12", "fraud_type_id": "ai_voice_impersonation", "count": 6},
    {"date": "2026-08-02", "fraud_type_id": "ai_voice_impersonation", "count": 5},
]


NEW_SCAM_PATTERNS = [
    {
        "id": "concert_ticket_takeover",
        "tag": "신종 감지",
        "title": "콘서트 양도 인증을 가장한 예매 계정 탈취",
        "summary": "티켓 양도 대화 중 예매 내역 확인이 필요하다며 로그인 링크를 보내고, 계정과 결제 정보를 가져가는 패턴이에요.",
        "red_flags": ["공식 앱 밖의 로그인 링크", "인증번호·비밀번호 재입력 요구"],
        "how_to_avoid": "양도 거래는 공식 플랫폼 안에서만 진행하고, 상대가 보낸 로그인 링크에는 들어가지 마세요.",
        "article_title": "관련 기사 확인 예정",
        "article_url": "",
        "date": "2026.08.13",
    },
    {
        "id": "ai_voice_impersonation",
        "tag": "신종 감지",
        "title": "AI 음성으로 지인 목소리를 흉내 내는 급전 요청",
        "summary": "짧은 음성 통화나 음성 메시지로 지인처럼 말하며 급히 송금을 부탁하는 사례를 가정한 데이터예요.",
        "red_flags": ["통화가 짧고 다시 걸면 받지 않음", "평소와 다른 계좌로 송금 요청"],
        "how_to_avoid": "가족·친구끼리만 아는 질문으로 확인하고, 기존 연락처로 다시 전화해 본인 여부를 확인하세요.",
        "article_title": "관련 기사 확인 예정",
        "article_url": "",
        "date": "2026.08.12",
    },
]


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def get_recent_report_counts(days: int = 30, today: date | None = None) -> dict[str, int]:
    """최근 N일 동안 fraud_type_id별 보고 건수를 집계한다."""
    today = today or date.today()
    start_date = today - timedelta(days=days - 1)
    counts: defaultdict[str, int] = defaultdict(int)

    for report in SCAM_REPORTS:
        reported_at = _parse_date(report["date"])
        if start_date <= reported_at <= today:
            counts[report["fraud_type_id"]] += report["count"]

    return dict(counts)


def get_newly_detected_scams(days: int = 30, today: date | None = None) -> list[dict]:
    """신종 감지 수법 목록에 최근 보고 건수를 붙여 반환한다."""
    counts = get_recent_report_counts(days=days, today=today)
    return [
        {**pattern, "reports_30d": counts.get(pattern["id"], 0)}
        for pattern in NEW_SCAM_PATTERNS
    ]
