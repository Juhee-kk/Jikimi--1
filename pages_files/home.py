import streamlit as st

import mock_data as data
from components import fmt, render_dark_band, render_footer_band, render_mascot

EMPATHY_BLOCK = {
    "quote": '"이 정도로 신고해도 되나?" 싶어서 그냥 넘긴 적 있죠.',
    "body": "그 순간에 쓰는 게 바로 저예요!",
}

ENTRY_CARDS = [
    {
        "icon": "💸",
        "title": "입금 직전인데 찜찜해요",
        "desc": "보내기 전에 확인해요",
        "color": "blue",
    },
    {
        "icon": "📱",
        "title": "이상한 문자를 받았어요",
        "desc": "눌렀는지에 따라 할 일이 달라요",
        "color": "green",
    },
    {
        "icon": "💬",
        "title": "대화 중 돈 얘기가 나왔어요",
        "desc": "한 마디로는 판단이 안 될 때",
        "color": "yellow",
    },
    {
        "icon": "🚨",
        "title": "이미 보냈어요",
        "desc": "지금이 제일 중요해요",
        "color": "coral",
    },
]

DIFFERENTIATORS = [
    {
        "num": "01",
        "title": "계좌 조회,\n그 이상을 봅니다",
        "body": "신고 이력이 없다고 안전한 게 아니에요. 대화 맥락 전체를 봐요.",
    },
    {
        "num": "02",
        "title": '"사기예요"를 넘어\n"어떻게 대응할지" 알려줘요',
        "body": "판정만 하고 끝내지 않아요. 지금 순서대로 할 일을 알려드려요.",
    },
    {
        "num": "03",
        "title": "매일 업데이트되는\n따끈한 사기 수법",
        "body": "매일 뉴스와 기관 발표를 업데이트해, 최신 수법을 놓치지 않아요.",
    },
]

HOW_IT_WORKS_STEPS = [
    {"num": 1, "title": "상황 공유하기", "desc": "받은 문자나 캡처본을 올려주세요"},
    {"num": 2, "title": "실시간 분석", "desc": "패턴을 같이 살펴봐요"},
    {"num": 3, "title": "안전한 선택", "desc": "위험도를 확인하고 진행하세요"},
]

TRUST_BADGES = [
    {"icon": "🔒", "label": "개인정보 보호", "desc": "주민번호·비밀번호는 절대 안 물어요"},
    {"icon": "🤝", "label": "판단 대신 안내", "desc": "지키미와 함께 해결해가요"},
    {"icon": "🛟", "label": "끝까지 함께", "desc": "대응 가이드까지 같이 봐요"},
]

DISCLAIMER_TEXT = (
    "텅장지키미의 진단은 참고용이에요. 최종 확인과 조치는 거래 은행, 경찰(112), "
    "금융감독원(1332)을 통해 진행해 주세요.\n"
    "급하면 지금 바로 은행 고객센터에 지급정지부터 요청하는 게 제일 빨라요."
)

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
empathy = EMPATHY_BLOCK
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
for i, (col, card) in enumerate(zip(card_cols, ENTRY_CARDS)):
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
for col, d in zip(diff_cols, DIFFERENTIATORS):
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
render_dark_band("지킴이와 함께하는 3단계", HOW_IT_WORKS_STEPS)

# --- 신뢰 배지 + 워드마크 (풀블리드 코랄 푸터 밴드) ---
render_footer_band("텅장지키미", "대한민국 청년의 텅장을 지키는 그날까지!", TRUST_BADGES)

st.markdown(f'<div style="text-align:center; font-size:0.72rem; opacity:0.55; margin-top:1.2rem;">{fmt(DISCLAIMER_TEXT)}</div>', unsafe_allow_html=True)
