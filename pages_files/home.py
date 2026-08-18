import streamlit as st

import mock_data as data
from components import (
    fmt,
    queue_chat_prefill,
    render_dark_band,
    render_footer_band,
    render_mascot,
    render_response_timeline,
)

# --- 히어로 (풀블리드 코랄) ---
hero = data.HERO_COPY
with st.container(key="hero_band"):
    copy_col, mascot_col = st.columns([1.75, 1], gap="medium")
    with copy_col:
        st.markdown(f'<div class="dj-headline" style="font-size:2.5rem; max-width:20ch;">{fmt(hero["title"])}</div>', unsafe_allow_html=True)
        st.markdown(f'<div style="font-size:1rem; margin-top:0.7rem; color:var(--ink-2); max-width:44ch; line-height:1.75;">{fmt(hero["subtitle"])}</div>', unsafe_allow_html=True)
        st.markdown("<div style='height:1.3rem'></div>", unsafe_allow_html=True)
        cta, _ = st.columns([1, 1.1])
        with cta:
            if st.button(hero["cta_label"], use_container_width=True, type="primary"):
                st.switch_page("pages_files/chat.py")
        st.markdown(f'<div style="font-size:0.78rem; color:var(--ink-3); margin-top:0.55rem;">{fmt(hero["cta_caption"])}</div>', unsafe_allow_html=True)
    with mascot_col:
        render_mascot(width=190, mood="calm")

st.markdown("<div style='height:2.2rem'></div>", unsafe_allow_html=True)

# --- 공감 블록 ---
empathy = data.EMPATHY_BLOCK
emp_icon, emp_text = st.columns([1, 6], gap="small")
with emp_icon:
    render_mascot(width=110, mood="warm")
with emp_text:
    st.markdown(
        f'''
        <div style="border-left:2px solid var(--ink); padding-left:1.1rem; max-width:60ch;">
            <div class="dj-headline" style="font-size:1.22rem;">{fmt(empathy["quote"])}</div>
            <div style="margin-top:0.45rem; color:var(--ink-2); font-size:0.9rem; line-height:1.78;">{fmt(empathy["body"])}</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )

st.markdown("<div style='height:1.8rem'></div>", unsafe_allow_html=True)

# --- 이럴 때 열어보세요 ---
card_cols = st.columns(4)
for i, (col, card) in enumerate(zip(card_cols, data.ENTRY_CARDS)):
    with col, st.container(key=f"entry_card_{i}"):
        st.markdown(
            f'''
            <div class="dj-{card["color"]}">
                <div class="dj-headline" style="font-size:0.97rem;">{fmt(card["title"])}</div>
                <div style="font-size:0.8rem; margin-top:0.3rem; color:var(--ink-2); line-height:1.6;">{fmt(card["desc"])}</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
        if st.button("물어보기", key=f"entry_{card['chip']}", use_container_width=True):
            queue_chat_prefill(card["chip"])

st.markdown("<div style='height:2.2rem'></div>", unsafe_allow_html=True)

# --- 차별성 3블록 (화이트 카드) ---
diff_cols = st.columns(3)
for col, d in zip(diff_cols, data.DIFFERENTIATORS):
    with col:
        st.markdown(
            f'''
            <div style="border-top:1px solid var(--rule); padding-top:0.85rem;">
                <div class="dj-fig" style="font-size:1.02rem; color:var(--ink-3);">{d["num"]}</div>
                <div class="dj-headline" style="font-size:1.03rem; margin-top:0.35rem;">{fmt(d["title"])}</div>
                <div style="margin-top:0.4rem; font-size:0.85rem; color:var(--ink-2); line-height:1.72;">{fmt(d["body"])}</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )

st.markdown("<div style='height:3rem'></div>", unsafe_allow_html=True)

# --- 대응 가이드 타임라인 (기존 대응가이드 페이지 → 홈 하단 통합) ---
render_response_timeline(data.TIMELINE_STEPS, data.TIMELINE_INTRO)

st.markdown(
    f'''<div style="margin-top:1.2rem; font-size:0.89rem; color:var(--ink-2); max-width:60ch;">{fmt(data.TIMELINE_FOOTER)}</div>''',
    unsafe_allow_html=True,
)

st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)
tl_left, _ = st.columns([1.4, 2])
with tl_left:
    if st.button("내 상황은 좀 다른데요", use_container_width=True, key="timeline_to_chat"):
        st.switch_page("pages_files/chat.py")

st.markdown("<div style='height:2.5rem'></div>", unsafe_allow_html=True)

# --- 사용 흐름 3스텝 (풀블리드 딥그린) ---
render_dark_band("지킴이와 함께하는 3단계", data.HOW_IT_WORKS_STEPS)

# --- 신뢰 배지 + 워드마크 (풀블리드 코랄 푸터 밴드) ---
render_footer_band("텅장지키미", "대한민국 청년의 텅장을 지키는 그날까지!", data.TRUST_BADGES)

st.markdown(f'<div style="font-size:0.72rem; color:var(--ink-3); margin-top:1.2rem; line-height:1.7;">{fmt(data.DISCLAIMER_TEXT)}</div>', unsafe_allow_html=True)