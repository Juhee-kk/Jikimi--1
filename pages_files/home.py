"""홈 화면. 서비스 소개와 상황 진단 탭으로의 진입점만 담당한다.

문구는 전부 content.py 에 있고 여기에는 레이아웃만 둔다.
히어로 CTA 와 진입 카드 4개가 상황 진단 탭으로 넘어가는 두 갈래 입구다.
카드는 눌린 카드의 chip 문구를 챗봇 첫 발화로 넘긴다(요즘 수법 탭 카드와 같은 방식).
"""

import streamlit as st

import content
from components import fmt, queue_chat_prefill, render_footer_band, render_mascot

# --- 히어로 (풀블리드 코랄) ---
hero = content.HERO_COPY
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
empathy = content.EMPATHY_BLOCK
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

# --- 이럴 때 열어보세요 (진입 카드 4개) ---
card_cols = st.columns(4)
for i, (col, card) in enumerate(zip(card_cols, content.ENTRY_CARDS)):
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
        if st.button("이 상황이에요 →", key=f"entry_card_cta_{i}", use_container_width=True):
            queue_chat_prefill(card["chip"])

st.markdown("<div style='height:2.2rem'></div>", unsafe_allow_html=True)

# --- 차별성 3블록 (화이트 카드) --- 그리드로 묶어 카드 높이를 서로 맞춤
# 주의: 마크다운이 4칸 들여쓰기를 코드블록으로 읽으므로 HTML은 한 줄로 붙여서 넘긴다.
diff_cards = "".join(
    f'<div class="dj-card dj-card-coral-tint">'
    f'<div style="font-size:1.5rem; opacity:0.45; font-weight:700; color: var(--dj-primary);">{d["num"]}</div>'
    f'<div class="dj-headline" style="font-size:1.1rem; margin-top:0.3rem;">{fmt(d["title"])}</div>'
    f'<div style="margin-top:0.5rem; font-size:0.85rem; opacity:0.85;">{fmt(d["body"])}</div>'
    f'</div>'
    for d in content.DIFFERENTIATORS
)
st.markdown(f'<div class="dj-grid-3">{diff_cards}</div>', unsafe_allow_html=True)

# --- 신뢰 배지 + 워드마크 (풀블리드 코랄 푸터 밴드) ---
render_footer_band(content.FOOTER_BAND_WORDMARK, content.FOOTER_BAND_TAGLINE, content.TRUST_BADGES)

st.markdown(f'<div style="text-align:center; font-size:0.72rem; opacity:0.55; margin-top:1.2rem;">{fmt(content.DISCLAIMER_TEXT)}</div>', unsafe_allow_html=True)
