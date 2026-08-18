from datetime import datetime

import streamlit as st

import mock_data as data
from components import (
    fmt,
    queue_chat_prefill,
    render_agency_section,
    render_fraud_type_card,
    render_monthly_stats,
    render_mascot,
    render_new_scam_alerts,
    render_quiz,
)

stats = data.MONTHLY_STATS

# --- 헤더 + 이번 달 건수 (우측 상단) ---
head_col, count_col = st.columns([3, 1])

with head_col:
    st.markdown(
        '''<div class="dj-eyebrow">월간 사기 동향</div>
        <div class="dj-headline" style="font-size:1.95rem; margin-top:0.3rem;">요즘 이런 게 돌아요</div>
        <div style="font-size:0.86rem; color:var(--ink-2); margin-top:0.4rem; max-width:52ch;">
            뉴스와 기관 발표에서 매일 수집해 정리합니다.</div>''',
        unsafe_allow_html=True,
    )

with count_col:
    st.markdown(
        f"""
        <div style="border-left:2px solid var(--ink); padding:0.15rem 0 0.15rem 0.9rem;">
            <div class="dj-eyebrow">{stats["month"]}</div>
            <div class="dj-fig" style="font-size:1.8rem; margin-top:0.25rem;">{stats["total_cases"]:,}<span
                 style="font-size:0.78rem; font-weight:500;">건</span></div>
            <div style="font-size:0.74rem; color:var(--ink-2); margin-top:0.25rem;">{stats["total_amount"]}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:1.4rem'></div>", unsafe_allow_html=True)

# --- 이번 달 통계 ---
render_monthly_stats(stats)

if st.session_state.get("history_log"):
    st.markdown(
        '''
        <div class="dj-card dj-card-yellow" style="margin-top:1rem;">
            \U0001F514 저번에 물어보신 거랑 비슷한 수법이 또 올라왔어요. 같은 조직이 계속 돌리는 중일 수 있어요.
        </div>
        ''',
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:2.2rem'></div>", unsafe_allow_html=True)

# --- 카테고리에 없는 신종 수법 ---
alert_icon, alert_body = st.columns([1, 7], gap="small")
with alert_icon:
    render_mascot(width=105, mood="alert")
with alert_body:
    render_new_scam_alerts(data.NEW_SCAM_ALERTS, data.NEW_SCAM_INTRO)

st.markdown("<div style='height:2.5rem'></div>", unsafe_allow_html=True)

# --- 이번 주 요약 + 카드뉴스 ---
summary = data.NEWS_WEEKLY_SUMMARY
st.markdown(
    f"""
    <div class="dj-card dj-card-dark">
        <strong>이번 주 한 줄 요약</strong><br>
        {summary["top_type"]}이 제일 많이 돌고 있어요. 특히 20대 대상으로요.<br>
        핵심은 하나예요 &mdash; <strong>"{summary["phrase"]}"</strong> 이 말이 나오면 그냥 끊으세요.
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f'<div style="font-size:0.78rem; opacity:0.55; margin-top:0.9rem;">\U0001F550 {datetime.now().strftime("%Y.%m.%d")} 기준 · 새로 올라온 소식 {len(data.NEWS_ARTICLES)}건</div>',
    unsafe_allow_html=True,
)
st.markdown("<div style='height:0.8rem'></div>", unsafe_allow_html=True)


@st.dialog("자세히 보기")
def show_article_detail(article: dict) -> None:
    st.markdown(
        f'<span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark);">{article["tag"]}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="dj-headline" style="font-size:1.25rem; margin-top:0.6rem;">{fmt(article["title"])}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.78rem; opacity:0.6; margin-top:0.3rem;">\U0001F4C5 {article["date"]} · \U0001F4C4 {article["source"]}</div>',
        unsafe_allow_html=True,
    )
    flags_html = "".join(f"<li>{fmt(f)}</li>" for f in article["red_flags"])
    st.markdown(
        f"""
        <p style="margin-top:0.9rem;"><strong>\U0001F50D 어떤 수법이냐면</strong><br>{fmt(article["summary"])}</p>
        <p><strong>\u26A0\uFE0F 이 말 나오면 의심하세요</strong></p>
        <ul>{flags_html}</ul>
        <p><strong>\U0001F6E1 이렇게 피해요</strong><br>{fmt(article["how_to_avoid"])}</p>
        """,
        unsafe_allow_html=True,
    )
    if st.button("이거 나한테 온 것 같아요 → 상담하기", use_container_width=True, key="dialog_news_cta"):
        queue_chat_prefill(f'"{article["title"]}" 이거랑 비슷한 걸 받았어요')


card_cols = st.columns(3)
for i, article in enumerate(data.NEWS_ARTICLES):
    with card_cols[i % 3], st.container(key=f"news_card_{i}"):
        st.markdown(
            f"""
            <div class="dj-card dj-card-white">
                <div style="font-size:2rem;">{article["icon"]}</div>
                <span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark); font-size:0.68rem; padding:0.2rem 0.7rem; margin-top:0.5rem; display:inline-block;">{article["tag"]}</span>
                <div class="dj-headline" style="font-size:0.98rem; margin-top:0.5rem; line-height:1.4;">{fmt(article["title"])}</div>
                <div style="font-size:0.78rem; margin-top:0.4rem; opacity:0.75; line-height:1.5;">{fmt(article["summary"])}</div>
                <div style="font-size:0.72rem; margin-top:0.7rem; opacity:0.55;">\U0001F4C5 {article["date"]}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        if st.button("자세히 보기 →", key=f"news_cta_{i}", use_container_width=True):
            show_article_detail(article)

st.markdown("<div style='height:2.8rem'></div>", unsafe_allow_html=True)

# --- 유형별 대응 카드 ---
st.markdown(
    f"""
    <div class="dj-section"><span class="num">05</span>
        <span class="ttl">유형별로 뭘 해야 하나</span>
        <span class="meta">{len(data.FRAUD_TYPES)}개 유형</span></div>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    f"""
    <div style="border-left:2px solid var(--seal); padding:0.1rem 0 0.1rem 0.95rem;
                margin:-0.6rem 0 1.5rem; max-width:74ch;">
        <div class="dj-eyebrow" style="color:var(--seal);">주의</div>
        <div style="font-size:0.85rem; line-height:1.75; margin-top:0.25rem;">
            <strong>전부 112로 지급정지가 되는 게 아닙니다.</strong> {fmt(data.REFUND_NOTICE)}</div></div>
    """,
    unsafe_allow_html=True,
)

st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)

type_cols = st.columns(3)
for i, ftype in enumerate(data.FRAUD_TYPES):
    with type_cols[i % 3]:
        render_fraud_type_card(ftype)

st.markdown("<div style='height:2.5rem'></div>", unsafe_allow_html=True)

# --- 신고·상담 기관 ---
render_agency_section(data.AGENCY_PHONE, data.AGENCY_ONLINE, data.BANK_CONTACTS)

st.markdown("<div style='height:2.8rem'></div>", unsafe_allow_html=True)

# --- 맨 아래: 감별 퀴즈 ---
st.session_state.setdefault("quiz_open", False)

if not st.session_state.quiz_open:
    st.markdown(
        '''
        <div style="border-top:2px solid var(--ink); padding-top:1.1rem;">
            <div class="dj-headline" style="font-size:1.15rem;">나는 안 당할까</div>
            <div style="font-size:0.85rem; color:var(--ink-2); margin-top:0.35rem;">
                몇 문제만 풀어보세요. 1분이면 끝나요.</div></div>
        ''',
        unsafe_allow_html=True,
    )
    qb, _ = st.columns([1, 3])
    with qb:
        if st.button("퀴즈 풀어보기", use_container_width=True, key="quiz_open_btn"):
            st.session_state.quiz_open = True
            st.rerun()
else:
    with st.container(key="quiz_box"):
        st.markdown('<div class="dj-headline" style="font-size:1.25rem;">감별 퀴즈</div>', unsafe_allow_html=True)
        render_quiz()
        st.markdown("<div style='height:0.6rem'></div>", unsafe_allow_html=True)
        if st.button("접기 ↑", key="quiz_close_btn"):
            st.session_state.quiz_open = False
            st.rerun()