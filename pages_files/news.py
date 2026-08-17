from datetime import datetime

import streamlit as st

import mock_data as data
from components import fmt, queue_chat_prefill, render_quiz

st.markdown('<div class="dj-headline" style="font-size:1.8rem;">📡 요즘 이런 게 돌아요</div>', unsafe_allow_html=True)
st.caption("뉴스랑 기관 발표에서 매일 긁어와서, 어려운 말은 다 걷어내고 정리했어요. 3줄만 읽어도 돼요.")

st.markdown(
    f'<div style="font-size:0.8rem; opacity:0.6;">🕐 {datetime.now().strftime("%Y.%m.%d")} 기준(mock) · 오늘 새로 올라온 소식 {len(data.NEWS_ARTICLES)}건</div>',
    unsafe_allow_html=True,
)

# --- 개인화 알림 배너 ---
if st.session_state.get("history_log"):
    st.markdown(
        '''
        <div class="dj-card dj-card-yellow" style="margin-top:1rem;">
            🔔 저번에 물어보신 거랑 비슷한 수법이 또 올라왔어요. 같은 조직이 계속 돌리는 중일 수 있어요.
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
        핵심은 하나예요 — <strong>"{summary["phrase"]}"</strong> 이 말이 나오면 그냥 끊으세요.
    </div>
    ''',
    unsafe_allow_html=True,
)

st.markdown("<div style='height:1.5rem'></div>", unsafe_allow_html=True)


@st.dialog("자세히 보기")
def show_article_detail(article: dict) -> None:
    st.markdown(
        f'<span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark);">{article["tag"]}</span>',
        unsafe_allow_html=True,
    )
    st.markdown(f'<div class="dj-headline" style="font-size:1.25rem; margin-top:0.6rem;">{fmt(article["title"])}</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div style="font-size:0.78rem; opacity:0.6; margin-top:0.3rem;">📅 {article["date"]} · 📄 {article["source"]}</div>',
        unsafe_allow_html=True,
    )
    flags_html = "".join(f"<li>{fmt(f)}</li>" for f in article["red_flags"])
    st.markdown(
        f'''
        <p style="margin-top:0.9rem;"><strong>🔍 어떤 수법이냐면</strong><br>{fmt(article["summary"])}</p>
        <p><strong>⚠️ 이 말 나오면 의심하세요</strong></p>
        <ul>{flags_html}</ul>
        <p><strong>🛡 이렇게 피해요</strong><br>{fmt(article["how_to_avoid"])}</p>
        ''',
        unsafe_allow_html=True,
    )
    if st.button("이거 나한테 온 것 같아요 → 상담하기", use_container_width=True, key="dialog_news_cta"):
        queue_chat_prefill(f'"{article["title"]}" 이거랑 비슷한 걸 받았어요')


# --- 카드뉴스(왼쪽 2/3) + 감별 퀴즈(오른쪽 1/3) ---
news_col, quiz_col = st.columns([2, 1])

with news_col:
    card_cols = st.columns(3)
    for i, article in enumerate(data.NEWS_ARTICLES):
        with card_cols[i % 3], st.container(key=f"news_card_{i}"):
            st.markdown(
                f'''
                <div class="dj-card dj-card-white">
                    <div style="font-size:2rem;">{article["icon"]}</div>
                    <span class="dj-badge" style="background:var(--dj-bg); color:var(--dj-primary-dark); font-size:0.68rem; padding:0.2rem 0.7rem; margin-top:0.5rem; display:inline-block;">{article["tag"]}</span>
                    <div class="dj-headline" style="font-size:0.98rem; margin-top:0.5rem; line-height:1.4;">{fmt(article["title"])}</div>
                    <div style="font-size:0.78rem; margin-top:0.4rem; opacity:0.75; line-height:1.5;">{fmt(article["summary"])}</div>
                    <div style="font-size:0.72rem; margin-top:0.7rem; opacity:0.55;">📅 {article["date"]}</div>
                </div>
                ''',
                unsafe_allow_html=True,
            )
            if st.button("자세히 보기 →", key=f"news_cta_{i}", use_container_width=True):
                show_article_detail(article)

with quiz_col:
    with st.container(key="quiz_box"):
        st.markdown('<div class="dj-headline" style="font-size:1.1rem;">🧠 감별 퀴즈</div>', unsafe_allow_html=True)
        render_quiz()
