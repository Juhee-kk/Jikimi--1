import streamlit as st

import mock_data as data
from components import fmt, render_dark_band, render_footer_band, render_mascot

# --- 히어로 (풀블리드 코랄) ---
hero = data.HERO_COPY
with st.container(key="hero_band"):
    with st.container(key="hero_mascot_slot"):
        render_mascot(width=200, name="mascot_alert")
    st.markdown(f'<div class="dj-headline" style="font-size:2.8rem; text-align:center;">{fmt(hero["title"])}</div>', unsafe_allow_html=True)
    st.markdown(f'<div style="font-size:1.05rem; margin-top:0.8rem; opacity:0.95; text-align:center;">{fmt(hero["subtitle"])}</div>', unsafe_allow_html=True)
    st.markdown("<div style='height:1.2rem'></div>", unsafe_allow_html=True)
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        if st.button(hero["cta_label"], use_container_width=True, type="primary"):
            st.switch_page("pages_files/chat.py")
    st.markdown(f'<div style="font-size:0.8rem; opacity:0.85; margin-top:0.6rem; text-align:center;">{fmt(hero["cta_caption"])}</div>', unsafe_allow_html=True)

st.markdown("<div style='height:2.2rem'></div>", unsafe_allow_html=True)

# --- 공감 블록 ---
empathy = data.EMPATHY_BLOCK
st.markdown(
    f'''
    <div style="text-align:center;">
        <div class="dj-headline" style="font-size:1.3rem;">{fmt(empathy["quote"])}</div>
        <div style="margin-top:0.5rem; opacity:0.7;">{fmt(empathy["body"])}</div>
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
            <div class="dj-card dj-card-{card["color"]}">
                <div style="font-size:1.8rem;">{card["icon"]}</div>
                <div style="font-weight:700; margin-top:0.5rem; color:var(--dj-white);">{fmt(card["title"])}</div>
                <div style="font-size:0.82rem; margin-top:0.3rem; color:var(--dj-white); opacity:0.85;">{fmt(card["desc"])}</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )

st.markdown("<div style='height:2.2rem'></div>", unsafe_allow_html=True)

# --- 차별성 3블록 (화이트 카드) ---
diff_cols = st.columns(3)
for col, d in zip(diff_cols, data.DIFFERENTIATORS):
    with col:
        st.markdown(
            f'''
            <div class="dj-card dj-card-coral-tint">
                <div style="font-size:1.5rem; opacity:0.45; font-weight:700; color: var(--dj-primary);">{d["num"]}</div>
                <div class="dj-headline" style="font-size:1.1rem; margin-top:0.3rem;">{fmt(d["title"])}</div>
                <div style="margin-top:0.5rem; font-size:0.85rem; opacity:0.85;">{fmt(d["body"])}</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )

# --- 사용 흐름 3스텝 (풀블리드 딥그린) ---
render_dark_band("지킴이와 함께하는 3단계", data.HOW_IT_WORKS_STEPS)

# --- 신뢰 배지 + 워드마크 (풀블리드 코랄 푸터 밴드) ---
render_footer_band("텅장지키미", "대한민국 청년의 텅장을 지키는 그날까지!", data.TRUST_BADGES)

st.markdown(f'<div style="text-align:center; font-size:0.72rem; opacity:0.55; margin-top:1.2rem;">{fmt(data.DISCLAIMER_TEXT)}</div>', unsafe_allow_html=True)
