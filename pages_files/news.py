import csv
import math
from html import escape
from pathlib import Path

import streamlit as st

import mock_data as data
from components import fmt, queue_chat_prefill, render_quiz

RECENT_REPORT_COUNTS = data.get_recent_report_counts(days=30)
NEWLY_DETECTED_SCAMS = data.get_newly_detected_scams(days=30)
VOICE_PHISHING_CSV = Path(__file__).resolve().parents[1] / "data" / "경찰청_보이스피싱 현황_20251231.csv"

st.markdown(
    """
    <style>
    .news-method-card {
        height: 188px;
        box-sizing: border-box;
        overflow: hidden;
    }
    .news-method-title {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .news-method-summary {
        display: -webkit-box;
        -webkit-line-clamp: 2;
        -webkit-box-orient: vertical;
        overflow: hidden;
    }
    .news-new-scam-card {
        height: auto !important;
        box-sizing: border-box;
    }
    .news-new-scam-body {
        display: grid;
        grid-template-columns: minmax(0, 1.25fr) minmax(260px, 0.75fr);
        gap: 1rem;
        margin-top: 0.5rem;
    }
    .news-new-scam-meta {
        display: flex;
        flex-wrap: wrap;
        gap: 0.45rem;
        margin-top: 0.7rem;
    }
    .news-new-scam-chip {
        border-radius: var(--dj-radius-pill);
        background: var(--dj-bg);
        padding: 0.24rem 0.72rem;
        font-size: 0.72rem;
        font-weight: 700;
        color: var(--dj-primary-dark);
    }
    .news-new-scam-link-btn {
        display: inline-flex;
        align-items: center;
        gap: 0.3rem;
        border-radius: var(--dj-radius-pill);
        background: var(--dj-primary-dark);
        padding: 0.24rem 0.9rem;
        font-size: 0.72rem;
        font-weight: 700;
        color: var(--dj-white) !important;
        text-decoration: none !important;
    }
    .news-new-scam-link-btn:hover {
        opacity: 0.85;
    }
    .news-new-scam-panel {
        border-left: 1px solid var(--dj-border);
        padding-left: 1rem;
        font-size: 0.78rem;
        line-height: 1.55;
    }
    .news-new-scam-panel ul {
        margin: 0.35rem 0 0;
        padding-left: 1.05rem;
    }
    div[class*="st-key-news_fixed_method_"],
    div[class*="st-key-news_new_method_"] {
        display: flex;
        flex-direction: column;
        height: 100%;
        margin-bottom: 1rem;
    }
    div[class*="st-key-news_fixed_method_"] .dj-card {
        height: 188px;
    }
    div[class*="st-key-news_fixed_method_"] .stButton > button {
        height: 40px;
        margin-top: 0.45rem;
    }
    div[class*="st-key-news_new_method_"] {
        background: var(--dj-white);
        border: 1px solid var(--dj-border);
        border-radius: var(--dj-radius-lg);
        box-shadow: 0 6px 20px rgba(43, 35, 32, 0.06);
        box-sizing: border-box;
        padding: 1.1rem 1.1rem 1.8rem;
        min-height: 214px;
    }
    div[class*="st-key-news_new_method_"] .stButton {
        height: 100%;
    }
    div[class*="st-key-news_new_method_"] .stButton > button {
        width: 2.75rem !important;
        min-height: 182px;
        margin-top: 0;
        padding: 0.8rem 0.35rem;
        white-space: nowrap;
        line-height: 1.1;
        writing-mode: vertical-rl;
        text-orientation: mixed;
    }
    @media (max-width: 760px) {
        .news-method-card,
        div[class*="st-key-news_fixed_method_"] .dj-card {
            height: 198px;
        }
        .news-new-scam-body {
            grid-template-columns: 1fr;
        }
        .news-new-scam-panel {
            border-left: 0;
            border-top: 1px solid var(--dj-border);
            padding-left: 0;
            padding-top: 0.8rem;
        }
        div[class*="st-key-news_new_method_"] .stButton > button {
            width: 2.65rem !important;
            min-height: 220px;
        }
    }
    .news-trend-highlight {
        text-align: right;
        display: flex;
        justify-content: flex-end;
        align-items: flex-end;
        min-height: 4.2rem;
    }
    .news-trend-highlight .news-trend-label {
        font-size: 0.78rem;
        opacity: 0.55;
    }
    .news-trend-highlight .news-trend-count {
        font-size: 1.9rem;
        font-weight: 800;
        margin-top: 0.2rem;
    }
    .news-trend-highlight .news-trend-amount {
        font-size: 0.85rem;
        opacity: 0.65;
        margin-top: 0.1rem;
    }
    .news-trend-divider {
        border-top: 1px solid var(--dj-border);
        margin: 1.4rem 0 1.2rem;
    }
    .news-trend-stat .news-trend-value {
        font-size: 1.7rem;
        font-weight: 800;
    }
    .news-trend-stat .news-trend-change {
        font-size: 0.75rem;
        opacity: 0.55;
        margin-top: 0.3rem;
    }
    .news-trend-stat .news-trend-label {
        font-size: 0.78rem;
        opacity: 0.55;
        margin-top: 0.15rem;
    }
    @media (max-width: 760px) {
        .news-trend-highlight {
            text-align: left;
            margin-top: 1rem;
        }
    }
    .news-evidence-grid {
        display: grid;
        grid-template-columns: minmax(0, 1.12fr) minmax(0, 0.88fr);
        gap: 1rem;
        margin-top: 0.9rem;
    }
    .news-chart-card {
        background: var(--dj-white);
        border: 1px solid var(--dj-border);
        border-radius: var(--dj-radius-lg);
        padding: 1.15rem 1.2rem;
        box-shadow: 0 6px 20px rgba(43, 35, 32, 0.06);
    }
    .news-governance-message {
        font-weight: 800;
        color: var(--dj-primary-dark);
        font-size: 1rem;
        line-height: 1.55;
    }
    .news-chart-svg {
        width: 100%;
        height: auto;
        display: block;
        margin-top: 0.8rem;
    }
    .news-chart-legend {
        display: flex;
        flex-wrap: wrap;
        gap: 0.55rem 0.85rem;
        margin-top: 0.8rem;
        font-size: 0.72rem;
        opacity: 0.74;
    }
    .news-legend-dot {
        display: inline-block;
        width: 0.62rem;
        height: 0.62rem;
        border-radius: 999px;
        margin-right: 0.28rem;
        vertical-align: -0.04rem;
    }
    .news-age-summary {
        display: grid;
        grid-template-columns: minmax(150px, 0.82fr) minmax(0, 1fr);
        align-items: center;
        gap: 1rem;
        margin-top: 0.95rem;
    }
    .news-pie-item {
        border: 1px solid var(--dj-border);
        border-radius: 16px;
        padding: 0.9rem 0.75rem;
        background: rgba(251, 243, 231, 0.42);
        text-align: center;
    }
    .news-pie-year {
        font-size: 0.8rem;
        font-weight: 800;
        color: var(--dj-primary-dark);
    }
    .news-age-list {
        display: grid;
        gap: 0.62rem;
    }
    .news-age-row {
        display: grid;
        grid-template-columns: auto 1fr auto;
        align-items: center;
        gap: 0.55rem;
        border-bottom: 1px solid rgba(43, 35, 32, 0.08);
        padding-bottom: 0.55rem;
        font-size: 0.78rem;
    }
    .news-age-row:last-child {
        border-bottom: 0;
        padding-bottom: 0;
    }
    .news-age-name {
        font-weight: 800;
        color: var(--dj-primary-dark);
    }
    .news-age-count {
        opacity: 0.6;
        text-align: right;
    }
    .news-age-percent {
        font-weight: 800;
        color: var(--dj-text);
    }
    .news-age-row.is-youth,
    .news-age-row.is-youth .news-age-name,
    .news-age-row.is-youth .news-age-count,
    .news-age-row.is-youth .news-age-percent {
        color: #D84A3A;
        opacity: 1;
    }
    .news-context-copy {
        margin-top: 1rem;
        font-size: 0.9rem;
        line-height: 1.8;
        color: rgba(43, 35, 32, 0.78);
    }
    .news-context-copy strong {
        color: var(--dj-primary-dark);
    }
    @media (max-width: 760px) {
        .news-evidence-grid,
        .news-age-summary {
            grid-template-columns: 1fr;
        }
        .news-chart-card {
            padding: 0.95rem;
        }
        .news-governance-message {
            font-size: 0.9rem;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def load_voice_phishing_rows() -> list[dict]:
    rows = []
    with VOICE_PHISHING_CSV.open(encoding="cp949", newline="") as csv_file:
        for row in csv.DictReader(csv_file):
            parsed = {
                "year": int(row["구분"]),
                "cases": int(row["총_발생건수"]),
                "damage": int(row["총_피해액_억원"]),
                "age_2030": int(row["20대이하"]) + int(row["30대"]),
                "age_4050": int(row["40대"]) + int(row["50대"]),
                "age_6070": int(row["60대"]) + int(row["70대이상"]),
            }
            parsed["age_total"] = parsed["age_2030"] + parsed["age_4050"] + parsed["age_6070"]
            parsed["age_2030_share"] = parsed["age_2030"] / parsed["age_total"] * 100
            rows.append(parsed)
    return rows


def fmt_pct(value: float) -> str:
    return f"{value:.1f}%"


def trend_change_label(current: int, previous: int, base_year: int) -> str:
    change = (current - previous) / previous * 100
    direction = "상승" if change >= 0 else "하락"
    return f"{base_year}년 대비 {abs(change):.1f}% {direction}"


def render_voice_combo_chart(rows: list[dict]) -> str:
    width, height = 780, 330
    left, right, top, bottom = 58, 118, 42, 48
    chart_w = width - left - right
    chart_h = height - top - bottom
    max_cases = max(row["cases"] for row in rows)
    max_damage = max(row["damage"] for row in rows)
    step = chart_w / len(rows)
    bar_w = min(34, step * 0.48)

    grid_lines = []
    for i in range(5):
        y = top + chart_h * i / 4
        grid_lines.append(f'<line x1="{left}" y1="{y:.1f}" x2="{width-right}" y2="{y:.1f}" stroke="rgba(43,35,32,0.10)" />')

    bars = []
    points = []
    year_labels = []
    for i, row in enumerate(rows):
        x = left + step * i + step / 2
        bar_h = row["cases"] / max_cases * chart_h
        y = top + chart_h - bar_h
        bars.append(
            f'<rect x="{x - bar_w / 2:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{bar_h:.1f}" '
            'rx="7" fill="#D8D2C8" opacity="0.95" />'
        )
        line_y = top + chart_h - row["damage"] / max_damage * chart_h
        points.append((x, line_y, row))
        if i % 2 == 0 or i == len(rows) - 1:
            year_labels.append(f'<text x="{x:.1f}" y="{height-19}" text-anchor="middle" font-size="22" fill="rgba(43,35,32,0.62)">{row["year"]}</text>')

    path_points = " ".join(f'{x:.1f},{y:.1f}' for x, y, _ in points)
    circles = [
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.5" fill="#D84A3A"><title>{row["year"]}년 피해액 {row["damage"]:,}억원</title></circle>'
        for x, y, row in points
    ]
    last_x, last_y, last_row = points[-1]
    annotations = (
        f'<rect x="{last_x - 152:.1f}" y="{last_y - 36:.1f}" width="124" height="26" rx="8" fill="#FFFFFF" opacity="0.94" />'
        f'<text x="{last_x - 34:.1f}" y="{last_y - 17:.1f}" text-anchor="end" font-size="18" font-weight="700" fill="#D84A3A">'
        f'{last_row["damage"]:,}억원</text>'
    )

    return (
        f'<svg class="news-chart-svg" viewBox="0 0 {width} {height}" role="img" aria-label="년도별 보이스피싱 발생건수와 피해액">'
        f'{"".join(grid_lines)}'
        f'{"".join(bars)}'
        f'<polyline points="{path_points}" fill="none" stroke="#D84A3A" stroke-width="5" stroke-linecap="round" stroke-linejoin="round" />'
        f'{"".join(circles)}{annotations}{"".join(year_labels)}'
        '</svg>'
    )


def pie_slice_path(cx: float, cy: float, radius: float, start: float, end: float) -> str:
    start_rad = math.radians(start - 90)
    end_rad = math.radians(end - 90)
    x1, y1 = cx + radius * math.cos(start_rad), cy + radius * math.sin(start_rad)
    x2, y2 = cx + radius * math.cos(end_rad), cy + radius * math.sin(end_rad)
    large_arc = 1 if end - start > 180 else 0
    return f"M {cx} {cy} L {x1:.3f} {y1:.3f} A {radius} {radius} 0 {large_arc} 1 {x2:.3f} {y2:.3f} Z"


def render_age_pie(row: dict) -> str:
    colors = {"age_2030": "#E2704F", "age_4050": "#F0C94A", "age_6070": "#1F3D34"}
    values = [("age_2030", row["age_2030"]), ("age_4050", row["age_4050"]), ("age_6070", row["age_6070"])]
    start = 0.0
    slices = []
    for key, value in values:
        end = start + value / row["age_total"] * 360
        slices.append(f'<path d="{pie_slice_path(60, 60, 48, start, end)}" fill="{colors[key]}" />')
        start = end
    return (
        '<svg class="news-chart-svg news-age-pie-svg" viewBox="0 0 120 120" role="img" '
        f'aria-label="{row["year"]}년 연령대별 피해 비중">'
        f'{"".join(slices)}'
        '<circle cx="60" cy="60" r="31" fill="#fffaf2" />'
        f'<text x="60" y="57" text-anchor="middle" font-size="14" font-weight="800" fill="#E2704F">{fmt_pct(row["age_2030_share"])}</text>'
        '<text x="60" y="74" text-anchor="middle" font-size="11" fill="rgba(43,35,32,0.62)">2030</text>'
        '</svg>'
    )


def render_age_breakdown(row: dict) -> str:
    colors = {"2030": "#E2704F", "4050": "#F0C94A", "6070": "#1F3D34"}
    groups = [
        ("2030", row["age_2030"]),
        ("4050", row["age_4050"]),
        ("6070", row["age_6070"]),
    ]
    return "".join(
        f'<div class="news-age-row {"is-youth" if label == "2030" else ""}">'
        f'<span><span class="news-legend-dot" style="background:{colors[label]};"></span><span class="news-age-name">{index}위 {label}</span></span>'
        f'<span class="news-age-count">{count:,}건</span>'
        f'<span class="news-age-percent">{fmt_pct(count / row["age_total"] * 100)}</span>'
        '</div>'
        for index, (label, count) in enumerate(groups, start=1)
    )


def render_voice_phishing_trends() -> None:
    rows = load_voice_phishing_rows()
    latest = rows[-1]
    previous = next(row for row in rows if row["year"] == latest["year"] - 1)
    average_youth_share = sum(row["age_2030_share"] for row in rows if 2019 <= row["year"] <= 2025) / 7

    head_col, highlight_col = st.columns([2, 1])
    with head_col:
        st.markdown(
            '<div class="dj-headline" style="font-size:1.8rem;">2025년, 당신의 통장은 안전했나요?</div>'
            '<div style="font-size:0.85rem; opacity:0.65; margin-top:0.4rem;"> 2025년 보이스피싱 통계에서 출발해, 청년층이 지금 조심해야 할 신종 수법까지 이어서 봅니다.</div>',
            unsafe_allow_html=True,
        )
    with highlight_col:
        st.markdown(
            '<div class="news-trend-highlight">'
            '<div class="news-trend-label">출처: 공공데이터_ 경찰청_보이스피싱 현황 통계자료</div>'
            '</div>',
            unsafe_allow_html=True,
        )

    st.markdown('<div class="news-trend-divider"></div>', unsafe_allow_html=True)

    stats = [
        {"value": f'{latest["cases"]:,}건', "change": trend_change_label(latest["cases"], previous["cases"], previous["year"]), "label": "2025년 발생건수"},
        {"value": f'{latest["damage"]:,}억원', "change": trend_change_label(latest["damage"], previous["damage"], previous["year"]), "label": "2025년 피해액"},
        {"value": fmt_pct(latest["age_2030_share"]), "change": f'2019~2025 평균 {fmt_pct(average_youth_share)}', "label": "20·30대 피해 비중"},
        {"value": f'{latest["damage"] / latest["cases"] * 10000:,.0f}만원', "change": None, "label": "1건당 평균 피해액"},
    ]
    stat_cols = st.columns(len(stats))
    for col, stat in zip(stat_cols, stats):
        with col:
            change_html = f'<div class="news-trend-change">{fmt(stat["change"])}</div>' if stat.get("change") else ""
            st.markdown(
                '<div class="news-trend-stat">'
                f'<div class="news-trend-value">{stat["value"]}</div>'
                f'{change_html}'
                f'<div class="news-trend-label">{stat["label"]}</div>'
                '</div>',
                unsafe_allow_html=True,
            )

    pie_item = (
        '<div class="news-pie-item">'
        f'<div class="news-pie-year">{latest["year"]} 연령별 피해비중</div>'
        f'{render_age_pie(latest)}'
        '</div>'
    )
    st.markdown(
        '<div class="news-evidence-grid">'
        '<div class="news-chart-card">'
        '<div class="news-governance-message">보이스피싱 피해액이 빠르게 증가하고 있어요.</div>'
        f'{render_voice_combo_chart(rows)}'
        '<div class="news-chart-legend">'
        '<span><span class="news-legend-dot" style="background:#D8D2C8;"></span>발생건수</span>'
        '<span><span class="news-legend-dot" style="background:#D84A3A;"></span>피해액(억원)</span>'
        '</div>'
        '</div>'
        '<div class="news-chart-card">'
        '<div class="news-governance-message">2030도 주요 타겟이에요.</div>'
        '<div class="news-context-copy" style="margin-top:0.45rem;">디지털에 익숙한 2030 또한 투자·부업·문자 링크처럼 온라인에서 시작되는 수법에 쉽게 노출될 수 있어요.</div>'
        f'<div class="news-age-summary">{pie_item}<div class="news-age-list">{render_age_breakdown(latest)}</div></div>'
        '</div>'
        '</div>'
        '<div class="news-context-copy">'
        '<strong>보이스피싱은 전화 한 통에서 끝나지 않고, 여러 디지털 수법으로 번지고 있어요.</strong> '
        '기관 사칭, 대출빙자형 보이스피싱뿐 아니라 투자 리딩방, 문자 링크, 중고거래, 로맨스 스캠처럼 돈을 보내게 만드는 수법이 더 다양해졌습니다. '
        '청년층에게 특히 자주 보이는 주요 수법을 먼저 모았습니다.'
        '</div>',
        unsafe_allow_html=True,
    )


render_voice_phishing_trends()

# --- 개인화 알림 배너 ---
if st.session_state.get("history_log"):
    st.markdown(
        '''
        <div class="dj-card dj-card-yellow" style="margin-top:1rem;">
            저번에 물어보신 거랑 비슷한 수법이 또 올라왔어요. 같은 조직이 계속 돌리는 중일 수 있어요.
        </div>
        ''',
        unsafe_allow_html=True,
    )

# --- 상단 요약 위젯 ---
st.markdown(
    '''
    <div class="dj-card dj-card-dark" style="margin-top:1rem;">
        <strong>청년층 대상 주요 수법은 다음과 같아요</strong><br>
        처음엔 전화 한 통, 문자 하나, 알바 제안 하나처럼 보여도 마지막엔 송금·대출·개인정보 요구로 이어집니다.<br>
        핵심은 하나예요. <strong>"먼저 돈을 넣어야 한다"</strong>는 말이 나오면 멈추고 확인하세요.
    </div>
    ''',
    unsafe_allow_html=True,
)

st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)


@st.dialog("수법 자세히 보기")
def show_method_detail(method: dict) -> None:
    st.markdown(
        f'<span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark);">{method["tag"]}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="dj-headline" style="font-size:1.25rem; margin-top:0.6rem;">{fmt(method["title"])}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.78rem; opacity:0.6; margin-top:0.3rem;">{method.get("date", "상시")} · {method.get("source", "고정 수법 DB")}</div>',
        unsafe_allow_html=True,
    )
    flags_html = "".join(f"<li>{fmt(f)}</li>" for f in method["red_flags"])
    actions_html = "".join(f"<li>{fmt(a)}</li>" for a in method.get("actions", []))
    action_block = f"<ol>{actions_html}</ol>" if actions_html else fmt(method["how_to_avoid"])
    st.markdown(
        f'''
        <p style="margin-top:0.9rem;"><strong>어떤 수법이냐면</strong><br>{fmt(method["summary"])}</p>
        <p><strong>이 말 나오면 의심하세요</strong></p>
        <ul>{flags_html}</ul>
        <p><strong>이렇게 피해요</strong><br>{action_block}</p>
        ''',
        unsafe_allow_html=True,
    )
    if st.button("이거 나한테 온 것 같아요 → 상담하기", use_container_width=True, key="dialog_news_cta"):
        queue_chat_prefill(f'"{method["title"]}" 이거랑 비슷한 걸 받았어요')


def fixed_method_view(type_dict: dict) -> dict:
    return {
        "icon": type_dict["icon"],
        "tag": "청년층 주요 수법",
        "title": type_dict["title"],
        "summary": type_dict["situation"],
        "red_flags": type_dict["red_flags"],
        "actions": type_dict["actions"],
        "warning": type_dict.get("warning"),
        "source": "고정 수법 DB",
        "reports_30d": RECENT_REPORT_COUNTS.get(type_dict["id"], 0),
    }


def render_method_card(method: dict, key_prefix: str, index: int) -> None:
    count = method.get("reports_30d")
    count_html = f'<div style="font-size:0.75rem; font-weight:700; opacity:0.72;">최근 1달 {count:,}건</div>' if count is not None else ""
    st.markdown(
        '<div class="dj-card dj-card-white news-method-card">'
        '<div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">'
        f'<div style="font-size:2rem; line-height:1;">{method["icon"]}</div>'
        f'{count_html}'
        '</div>'
        f'<span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark); font-size:0.68rem; padding:0.2rem 0.7rem; margin-top:0.7rem; display:inline-block;">{method["tag"]}</span>'
        f'<div class="dj-headline news-method-title" style="font-size:1rem; margin-top:0.55rem; line-height:1.4;">{fmt(method["title"])}</div>'
        f'<div class="news-method-summary" style="font-size:0.78rem; margin-top:0.45rem; opacity:0.75; line-height:1.55;">{fmt(method["summary"])}</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    if st.button("자세히 보기 →", key=f"{key_prefix}_cta_{index}", use_container_width=True):
        show_method_detail(method)


def render_new_scam_card(method: dict, index: int) -> None:
    flags_html = "".join(f"<li>{fmt(flag)}</li>" for flag in method["red_flags"][:2])
    article_title = method.get("article_title") or "관련 기사"
    article_url = method.get("article_url")
    article_html = (
        f'<a class="news-new-scam-link-btn" href="{escape(article_url, quote=True)}" target="_blank" rel="noopener noreferrer">🔗 {fmt(article_title)}</a>'
        if article_url
        else f'<span class="news-new-scam-chip">{fmt(article_title)}</span>'
    )
    content_col, action_col = st.columns([32, 1], gap="small")
    with content_col:
        st.markdown(
            f'''
            <div class="news-new-scam-card">
                <span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark); font-size:0.68rem; padding:0.2rem 0.7rem; display:inline-block;">{method["tag"]}</span>
                <div class="news-new-scam-body">
                    <div>
                        <div class="dj-headline" style="font-size:1.05rem; line-height:1.4;">{fmt(method["title"])}</div>
                        <div style="font-size:0.82rem; opacity:0.76; line-height:1.6; margin-top:0.5rem;">{fmt(method["summary"])}</div>
                        <div class="news-new-scam-meta">
                            <span class="news-new-scam-chip">감지일 {method.get("date", "확인 중")}</span>
                            {article_html}
                        </div>
                    </div>
                    <div class="news-new-scam-panel">
                        <strong>이 말 나오면 의심하세요</strong>
                        <ul>{flags_html}</ul>
                        <div style="margin-top:0.65rem;"><strong>이렇게 피해요</strong><br>{fmt(method["how_to_avoid"])}</div>
                    </div>
                </div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
    with action_col:
        if st.button("상담하기", key=f"new_method_chat_{index}", use_container_width=True):
            queue_chat_prefill(f'"{method["title"]}" 이거랑 비슷한 걸 받았어요')


st.markdown('<div class="dj-headline" style="font-size:1.35rem; margin-top:0.4rem;">1. 청년층 대상 주요 수법 8가지</div>', unsafe_allow_html=True)
st.caption("자주 반복되는 8가지 수법을 먼저 확인해보세요.")

fixed_methods = [fixed_method_view(type_dict) for type_dict in data.FRAUD_TYPES]
fixed_cols = st.columns(4)
for i, method in enumerate(fixed_methods):
    with fixed_cols[i % 4], st.container(key=f"news_fixed_method_{i}"):
        render_method_card(method, "fixed_method", i)

st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
st.markdown('<div class="dj-headline" style="font-size:1.35rem;">2. 신종 감지된 수법</div>', unsafe_allow_html=True)
st.caption("기존 분류에 딱 들어맞지 않는 새 패턴을 따로 모아볼 수 있어요.")

if NEWLY_DETECTED_SCAMS:
    for i, method in enumerate(NEWLY_DETECTED_SCAMS):
        with st.container(key=f"news_new_method_{i}"):
            render_new_scam_card(method, i)
else:
    st.markdown(
        f'''
        <div class="dj-card dj-card-white" style="text-align:center;">
            {fmt(data.NEWS_EMPTY_STATES["no_new"])}
        </div>
        ''',
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:1.6rem'></div>", unsafe_allow_html=True)
st.markdown('<div class="dj-headline" style="font-size:1.35rem;">3. 퀴즈 섹션</div>', unsafe_allow_html=True)
with st.container(key="quiz_box"):
    render_quiz()
