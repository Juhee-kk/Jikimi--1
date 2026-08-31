import streamlit as st

import mock_data as data
from components import fmt, render_footer_band, render_mascot

EMPATHY_BLOCK = {
    "quote": '"이 정도로 신고해도 되나?" 싶어서 그냥 넘긴 적 있죠.',
    "body": "그 순간에 쓰는 게 바로 저예요!",
}

ENTRY_CARDS = [
     {
            "icon": "💸",
            "title": "입금 직전인데 찜찜해요",
            "desc": "보내기 전에 확인해요",
            "chip": "💸 입금하기 직전이에요",
            "color": "blue",
        },
        {
            "icon": "📱",
            "title": "이상한 문자를 받았어요",
            "desc": "첨부된 링크가 있었는지, 눌렀는지에 따라 할 일이 달라요",
            "chip": "📩 이상한 문자를 받았어요",
            "color": "green",
        },
        {
            "icon": "💬",
            "title": "대화 중 돈 얘기가 나왔어요",
            "desc": "한두 마디로는 판단이 안 될 때, 상황 맥락 전체를 확인해요",
            "chip": "💬 온라인에서 만난 사람이 돈을 요구해요",
            "color": "yellow",
        },
        {
            "icon": "🚨",
            "title": "이미 보냈어요",
            "desc": "지금이 제일 중요해요. 지금부터 할 일을 순서대로 확인해요",
            "chip": "🚨 이미 돈을 보냈어요",
            "color": "coral",
        },
]

DIFFERENTIATORS = [
    {
            "num": "01",
            "title": "계좌 조회,그 이상을 봅니다",
            "body": "신고 이력이 없다고 안전한 게 아니에요.\n비슷한 사례가 있는지 확인이 필요해요.\n ",
        },
        {
            "num": "02",
            "title": '확인에서 끝나지 않고 대응 방법까지 알려드려요',
            "body": "갑작스러운 상황에서는 뭘 먼저 해야 할지 모를 수 있어요.\n지금 상황에 맞춰 필요한 확인과 대응을 순서대로 안내해드릴게요.\n ",
        },
        {
            "num": "03",
            "title": "매일 업데이트되는 따끈한 사기 수법",
            "body": "뉴스와 공식 기관에서 공개한 사기 사례를 매일 모아 정리해요.\n‘요즘 수법’ 탭에서 최근 사례와 주요 수법을 확인할 수 있고,\n‘상담할 때도 최신 수법을 기준으로 확인해요.",
        },
]

TRUST_BADGES = [
    {"icon": "📰", "label": "요즘 수법 한눈에", "desc": "매일 업데이트되는 수법을 확인해요"},
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

# --- 차별성 3블록 (화이트 카드) --- 그리드로 묶어 카드 높이를 서로 맞춤
# 주의: 마크다운이 4칸 들여쓰기를 코드블록으로 읽으므로 HTML은 한 줄로 붙여서 넘긴다.
diff_cards = "".join(
    f'<div class="dj-card dj-card-coral-tint">'
    f'<div style="font-size:1.5rem; opacity:0.45; font-weight:700; color: var(--dj-primary);">{d["num"]}</div>'
    f'<div class="dj-headline" style="font-size:1.1rem; margin-top:0.3rem;">{fmt(d["title"])}</div>'
    f'<div style="margin-top:0.5rem; font-size:0.85rem; opacity:0.85;">{fmt(d["body"])}</div>'
    f'</div>'
    for d in DIFFERENTIATORS
)
st.markdown(f'<div class="dj-grid-3">{diff_cards}</div>', unsafe_allow_html=True)

# --- 신뢰 배지 + 워드마크 (풀블리드 코랄 푸터 밴드) ---
render_footer_band("텅장지키미", "대한민국 청년의 텅장을 지키는 그날까지!", TRUST_BADGES)

st.markdown(f'<div style="text-align:center; font-size:0.72rem; opacity:0.55; margin-top:1.2rem;">{fmt(DISCLAIMER_TEXT)}</div>', unsafe_allow_html=True)
