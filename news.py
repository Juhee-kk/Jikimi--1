from datetime import datetime
from html import escape

import streamlit as st

import mock_data as data
import news_data
from components import fmt, queue_chat_prefill, render_quiz

RECENT_REPORT_COUNTS = news_data.get_recent_report_counts(days=30)
NEWLY_DETECTED_SCAMS = news_data.get_newly_detected_scams(days=30)

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
        margin-top: 0.65rem;
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
    .news-new-scam-chip a {
        color: inherit;
        text-decoration: none;
    }
    .news-new-scam-head {
        display: flex;
        gap: 0.55rem;
        align-items: center;
        min-width: 0;
    }
    .news-new-scam-title-wrap {
        min-width: 0;
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
        padding: 1.1rem;
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
        .news-new-scam-head {
            align-items: flex-start;
        }
        div[class*="st-key-news_new_method_"] .stButton > button {
            width: 2.65rem !important;
            min-height: 220px;
        }
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="dj-headline" style="font-size:1.8rem;">요즘 수법 탭</div>', unsafe_allow_html=True)
st.caption("청년층이 자주 마주치는 주요 수법과 새롭게 감지된 낯선 패턴을 나눠 정리했어요.")

st.markdown(
    f'<div style="font-size:0.8rem; opacity:0.6;">{datetime.now().strftime("%Y.%m.%d")} 기준 · 최근 1달 보고 건수 집계</div>',
    unsafe_allow_html=True,
)

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
summary = data.NEWS_WEEKLY_SUMMARY
st.markdown(
    f'''
    <div class="dj-card dj-card-dark" style="margin-top:1rem;">
        <strong>이번 주 한 줄 요약</strong><br>
        {summary["top_type"]}이 제일 많이 돌고 있어요. 특히 20대 대상으로요.<br>
        핵심은 하나예요. <strong>"{summary["phrase"]}"</strong> 이 말이 나오면 그냥 끊으세요.
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
        f'''
        <div class="dj-card dj-card-white news-method-card">
            <div style="display:flex; justify-content:space-between; gap:0.75rem; align-items:flex-start;">
                <div style="font-size:2rem; line-height:1;">{method["icon"]}</div>
                {count_html}
            </div>
            <span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark); font-size:0.68rem; padding:0.2rem 0.7rem; margin-top:0.7rem; display:inline-block;">{method["tag"]}</span>
            <div class="dj-headline news-method-title" style="font-size:1rem; margin-top:0.55rem; line-height:1.4;">{fmt(method["title"])}</div>
            <div class="news-method-summary" style="font-size:0.78rem; margin-top:0.45rem; opacity:0.75; line-height:1.55;">{fmt(method["summary"])}</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )
    if st.button("자세히 보기 →", key=f"{key_prefix}_cta_{index}", use_container_width=True):
        show_method_detail(method)


def render_new_scam_card(method: dict, index: int) -> None:
    count = method.get("reports_30d", 0)
    flags_html = "".join(f"<li>{fmt(flag)}</li>" for flag in method["red_flags"][:2])
    article_title = method.get("article_title") or "관련 기사"
    article_url = method.get("article_url")
    article_html = (
        f'<a href="{escape(article_url, quote=True)}" target="_blank" rel="noopener noreferrer">{fmt(article_title)}</a>'
        if article_url
        else fmt(article_title)
    )
    content_col, action_col = st.columns([32, 1], gap="small")
    with content_col:
        st.markdown(
            f'''
            <div class="news-new-scam-card">
                <div style="display:flex; justify-content:space-between; gap:1rem; align-items:flex-start;">
                    <div class="news-new-scam-head">
                        <div class="news-new-scam-title-wrap">
                            <span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark); font-size:0.68rem; padding:0.2rem 0.7rem; display:inline-block;">{method["tag"]}</span>
                            <div class="dj-headline" style="font-size:1.05rem; line-height:1.4; margin-top:0.35rem;">{fmt(method["title"])}</div>
                        </div>
                    </div>
                    <div style="font-size:0.75rem; font-weight:700; opacity:0.72; text-align:right;">최근 1달 {count:,}건</div>
                </div>
                <div class="news-new-scam-body">
                    <div>
                        <div style="font-size:0.82rem; opacity:0.76; line-height:1.6;">{fmt(method["summary"])}</div>
                        <div class="news-new-scam-meta">
                            <span class="news-new-scam-chip">감지일 {method.get("date", "확인 중")}</span>
                            <span class="news-new-scam-chip">{article_html}</span>
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
