"""여러 페이지가 함께 쓰는 UI 조각.

한 페이지에서만 쓰는 렌더 함수는 그 페이지 파일에 둔다
(예: 퀴즈는 pages_files/news.py, 뉴스 카드도 news.py).
여기 남는 것은 전역 CSS, 상단 내비, 푸터, 말풍선, 마스코트처럼 화면을 가로지르는 것들이다.
"""

from __future__ import annotations

import html as html_lib
import io
import re
from collections import deque
from pathlib import Path

import streamlit as st
from PIL import Image

from content import FOOTER_TEXT


def fmt(text: str) -> str:
    """일반 텍스트를 안전하게 escape하고 **bold**, 줄바꿈만 HTML로 변환."""
    escaped = html_lib.escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
    return escaped.replace("\n", "<br>")


# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

def inject_custom_css() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Gaegu:wght@400;700&family=Gowun+Dodum&display=swap');

        :root {
            --dj-bg: #FBF3E7;
            --dj-primary: #E2704F;
            --dj-primary-dark: #1F3D34;
            --dj-text: #2B2320;
            --dj-card-blue: #AEDCEA;
            --dj-card-green: #B9DCAE;
            --dj-card-yellow: #F0C94A;
            --dj-card-coral: #E8896F;
            --dj-white: #FFFFFF;
            --dj-border: rgba(43, 35, 32, 0.10);
            --dj-radius-lg: 24px;
            --dj-radius-pill: 999px;
        }

        html, body, [class*="css"], .stApp, .stMarkdown, p, span, div, li {
            font-family: 'Gowun Dodum', 'Gaegu', -apple-system, 'Malgun Gothic', sans-serif;
        }

        html, body, .stApp { overflow-x: hidden; }
        .stApp { background-color: var(--dj-bg); color: var(--dj-text); }
        [data-testid="stHeader"] { background-color: transparent; height: 0 !important; min-height: 0 !important; }
        [data-testid="stAppViewContainer"] > .main { padding-top: 1.2rem !important; }
        section.main { padding-top: 1.2rem !important; }
        [data-testid="stAppViewContainer"] > .main .block-container { padding-top: 0 !important; margin-top: 0 !important; max-width: 1080px; }
        [data-testid="stMainBlockContainer"] { padding-top: 1cm !important; margin-top: 0 !important; }

        .dj-headline { font-family: 'Gaegu', 'Gowun Dodum', sans-serif; font-weight: 700; line-height: 1.3; }

        /* --- 상단 내비게이션 --- */
        .dj-logo {
            font-family: 'Gaegu', sans-serif; font-weight: 700; font-size: 3.2rem;
            color: var(--dj-primary-dark); padding-top: 0.2rem;
            position: relative; left: -1cm; top: -1cm;
        }
        [data-testid="stPageLink"] {
            border-radius: var(--dj-radius-pill) !important;
            padding: 0.3rem 0.9rem !important;
            background: var(--dj-white);
            border: 1px solid var(--dj-border);
        }
        [data-testid="stPageLink"] p { font-weight: 600 !important; }
        [data-testid="stPageLink"][aria-current="page"] {
            background: var(--dj-primary) !important;
        }
        [data-testid="stPageLink"][aria-current="page"] p { color: var(--dj-white) !important; }

        /* --- 버튼 --- */
        .stButton > button {
            border-radius: var(--dj-radius-pill);
            font-weight: 700;
            border: none;
        }
        .stButton > button[kind="primary"] {
            background-color: var(--dj-primary);
            color: var(--dj-white);
        }

        /* --- 풀블리드 섹션 (순수 HTML 블록: 3단계/푸터 밴드용, 위젯 없음) --- */
        .dj-full-bleed {
            position: relative;
            left: 50%;
            right: 50%;
            margin-left: -50vw !important;
            margin-right: -50vw !important;
            width: 100vw;
            box-sizing: border-box;
            padding: 2.6rem max(1.5rem, calc(50vw - 540px + 1.5rem));
            text-align: center;
        }
        .dj-full-bleed-inner { max-width: 1080px; margin: 0 auto; }

        /* 히어로 (코랄, 가로로 쭉 이어지는 배너 — 둥근 모서리 없음)
           st.columns/버튼이 들어있는 실제 컨텐츠 박스는 폭을 건드리지 않고,
           ::before 가상 요소만 뷰포트 끝까지 배경을 확장해서 내부 레이아웃이 깨지지 않게 함. */
        div[class*="st-key-hero_band"] {
            position: relative;
            color: var(--dj-white);
            padding: 3.2rem 1rem 2.4rem;
            z-index: 0;
        }
        div[class*="st-key-hero_band"]::before {
            content: "";
            position: absolute;
            top: 0; bottom: 0;
            left: 50%;
            width: 100vw;
            margin-left: -50vw;
            background: var(--dj-primary);
            z-index: -1;
        }
        div[class*="st-key-hero_band"] .stButton { display: flex; justify-content: center; }
        div[class*="st-key-hero_band"] .stButton > button {
            background-color: var(--dj-primary-dark); color: var(--dj-white);
            padding: 0.7rem 2.2rem; font-size: 1.05rem;
        }

        /* 마스코트 프레임 */
        div[class*="st-key-mascot_frame"] {
            display: flex; align-items: center; justify-content: center;
            min-height: 200px;
        }
        div[class*="st-key-mascot_frame"] img {
            filter: drop-shadow(0 14px 22px rgba(31, 61, 52, 0.35));
        }

        /* 히어로 마스코트 — 가운데 문구는 그대로 두고, 빈 공간에만 얹히는 오버레이 */
        div[class*="st-key-hero_mascot_slot"] {
            position: absolute;
            left: clamp(0.5rem, 4vw, 4rem);
            top: 50%;
            transform: translateY(-50%);
            width: fit-content !important;
            z-index: 1;
            pointer-events: none;
        }
        @media (max-width: 900px) {
            div[class*="st-key-hero_mascot_slot"] { display: none; }
        }

        /* 3단계 (딥그린) */
        .dj-full-bleed.dj-dark { background: var(--dj-primary-dark); color: var(--dj-white); margin-top: 2rem; }

        /* 푸터 밴드 (코랄, 상단 라운드) */
        .dj-full-bleed.dj-footer-band { background: var(--dj-primary); color: var(--dj-white); border-radius: 56px 56px 0 0; margin-top: 2.5rem; padding-top: 3rem; }

        /* 홈 — 진입 카드 4개 (카드 + 하단 CTA 버튼 높이 맞춤) */
        div[class*="st-key-entry_card_"] { display: flex; flex-direction: column; height: 100%; }
        div[class*="st-key-entry_card_"] .dj-card { flex: 1; min-height: 158px; }
        div[class*="st-key-entry_card_"] .stButton { margin-top: 0.5rem; }
        div[class*="st-key-entry_card_"] .stButton > button {
            background: var(--dj-white); border: 1px solid var(--dj-border);
            font-size: 0.82rem; height: 40px;
        }

        /* 요즘 수법 — 카드뉴스 */
        div[class*="st-key-news_card_"] { display: flex; flex-direction: column; height: 100%; margin-bottom: 1rem; }
        div[class*="st-key-news_card_"] .dj-card { padding: 1.1rem; flex: 1; }
        div[class*="st-key-news_card_"] .stButton { margin-top: 0.5rem; }

        /* 요즘 수법 — 감별 퀴즈 세로 박스 */
        div[class*="st-key-quiz_box"] {
            background: var(--dj-white);
            border: 1px solid var(--dj-border);
            border-radius: var(--dj-radius-lg);
            padding: 1.4rem;
            min-height: 100%;
        }

        /* --- 카드 공통 --- */
        .dj-card {
            border-radius: var(--dj-radius-lg);
            padding: 1.4rem;
            height: 100%;
            box-shadow: 0 6px 20px rgba(43, 35, 32, 0.06);
        }
        .dj-card-white { background: var(--dj-white); border: 1px solid var(--dj-border); }
        .dj-card-coral-tint { background: rgba(226, 112, 79, 0.10); border: 1px solid rgba(226, 112, 79, 0.35); }
        .dj-card-dark { background: var(--dj-primary-dark); color: var(--dj-white); }
        .dj-card-blue { background: var(--dj-card-blue); }
        .dj-card-green { background: var(--dj-card-green); }
        .dj-card-yellow { background: var(--dj-card-yellow); }
        .dj-card-coral { background: var(--dj-card-coral); color: var(--dj-white); }

        /* 동일 높이 3열 그리드 (위젯 없는 순수 카드용) */
        .dj-grid-3 {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1rem;
            align-items: stretch;
        }
        @media (max-width: 900px) {
            .dj-grid-3 { grid-template-columns: 1fr; }
        }

        /* --- 위험도 배지 --- */
        .dj-badge {
            display: inline-block;
            padding: 0.25rem 0.9rem;
            border-radius: var(--dj-radius-pill);
            font-weight: 700;
            font-size: 0.85rem;
        }

        /* --- 채팅 말풍선 --- */
        .dj-chat-row { display: flex; margin-bottom: 0.9rem; }
        .dj-chat-row.user { justify-content: flex-end; }
        .dj-chat-row.assistant { justify-content: flex-start; }
        .dj-bubble {
            max-width: 72%;
            padding: 0.75rem 1.1rem;
            border-radius: 20px;
            line-height: 1.55;
            font-size: 0.95rem;
        }
        .dj-bubble.user { background: var(--dj-primary-dark); color: var(--dj-white); border-bottom-right-radius: 4px; }
        .dj-bubble.assistant { background: var(--dj-white); color: var(--dj-text); border: 1px solid var(--dj-border); border-bottom-left-radius: 4px; }

        /* --- 타임라인 --- */
        .dj-timeline-item { display: flex; gap: 1rem; padding-bottom: 1.6rem; position: relative; }
        .dj-timeline-item:not(:last-child)::before {
            content: ""; position: absolute; left: 11px; top: 26px; bottom: -6px; width: 2px; background: var(--dj-border);
        }
        .dj-timeline-dot {
            width: 24px; height: 24px; border-radius: 50%; flex-shrink: 0;
            display: flex; align-items: center; justify-content: center; margin-top: 2px;
        }

        /* --- 푸터 --- */
        .dj-footer {
            margin-top: 2.5rem;
            padding: 1.2rem 0 2rem 0;
            border-top: 1px solid var(--dj-border);
            font-size: 0.8rem;
            color: rgba(43, 35, 32, 0.65);
            text-align: center;
            line-height: 1.6;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# 레이아웃 (상단 내비 · 푸터)
# ---------------------------------------------------------------------------

def render_top_nav(pages: list) -> None:
    logo_col, *nav_cols = st.columns([3] + [1] * len(pages))
    with logo_col:
        st.markdown('<div class="dj-logo">🛡️ 텅장지키미</div>', unsafe_allow_html=True)
    for col, page in zip(nav_cols, pages):
        with col:
            st.page_link(page, use_container_width=True)


def render_footer() -> None:
    st.markdown(f'<div class="dj-footer">{fmt(FOOTER_TEXT)}</div>', unsafe_allow_html=True)


def render_footer_band(wordmark: str, tagline: str, badges: list[dict]) -> None:
    """코랄 풀블리드 하단 밴드 (워드마크 + 신뢰 배지)."""
    badges_html = "".join(
        f'''
        <div style="flex:1; min-width:140px;">
            <div style="font-size:1.4rem;">{b["icon"]}</div>
            <div style="font-weight:700; margin-top:0.3rem;">{fmt(b["label"])}</div>
            <div style="font-size:0.78rem; margin-top:0.2rem; opacity:0.85;">{fmt(b["desc"])}</div>
        </div>
        '''
        for b in badges
    )
    st.markdown(
        f'''
        <div class="dj-full-bleed dj-footer-band"><div class="dj-full-bleed-inner">
            <div class="dj-headline" style="font-size:1.8rem;">{fmt(wordmark)}</div>
            <div style="margin-top:0.4rem; opacity:0.9;">{fmt(tagline)}</div>
            <div style="display:flex; gap:1.5rem; flex-wrap:wrap; justify-content:center; margin-top:1.8rem;">{badges_html}</div>
        </div></div>
        ''',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# 대화 · 페이지 이동
# ---------------------------------------------------------------------------

def render_chat_message(role: str, content: str) -> None:
    bubble_class = "user" if role == "user" else "assistant"
    st.markdown(
        f'<div class="dj-chat-row {bubble_class}"><div class="dj-bubble {bubble_class}">{fmt(content)}</div></div>',
        unsafe_allow_html=True,
    )


def queue_chat_prefill(text: str) -> None:
    """홈/뉴스 카드에서 클릭 시 상황 진단 페이지로 이동하며 첫 메시지를 예약."""
    st.session_state["prefill_chip"] = text
    st.switch_page("pages_files/chat.py")


# ---------------------------------------------------------------------------
# 마스코트
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner=False)
def _cutout_white_bg(path_str: str, mtime: float) -> bytes:
    """PNG의 흰색/회색조(체크무늬 포함) 배경을 투명으로 바꿔서 캐릭터만 남김.

    가장자리에서 시작해 무채색(R≈G≈B) 픽셀을 flood fill로 따라가며 지운다 —
    일부 내보내기 도구가 진짜 알파 채널 대신 회색 체크무늬를 배경에 그대로
    구워 넣는 경우가 있어서, 단순 흰색 임계값만으로는 배경이 안 지워짐.
    mtime을 캐시 키로 써서 파일 교체 시 자동 갱신.
    """
    img = Image.open(path_str).convert("RGBA")
    w, h = img.size
    px = img.load()

    def is_bg(p: tuple[int, int, int, int]) -> bool:
        r, g, b, _a = p
        return abs(r - g) <= 10 and abs(g - b) <= 10 and abs(r - b) <= 10

    visited = bytearray(w * h)
    queue: deque[tuple[int, int]] = deque()

    def seed(x: int, y: int) -> None:
        idx = y * w + x
        if not visited[idx] and is_bg(px[x, y]):
            visited[idx] = 1
            queue.append((x, y))

    for x in range(w):
        seed(x, 0)
        seed(x, h - 1)
    for y in range(h):
        seed(0, y)
        seed(w - 1, y)

    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if 0 <= nx < w and 0 <= ny < h and not visited[ny * w + nx] and is_bg(px[nx, ny]):
                visited[ny * w + nx] = 1
                queue.append((nx, ny))

    for y in range(h):
        for x in range(w):
            if visited[y * w + x]:
                r, g, b, _a = px[x, y]
                px[x, y] = (r, g, b, 0)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _has_real_transparency(path_str: str) -> bool:
    """이미 알파 채널로 투명 처리된 PNG인지 확인 (흰/회색 배경을 굽지 않고 내보낸 경우)."""
    img = Image.open(path_str)
    if img.mode != "RGBA":
        return False
    return img.getextrema()[3][0] < 250


def render_mascot(width: int = 260, name: str = "mascot") -> None:
    """assets/ 폴더의 마스코트 파일을 보여줌.

    우선순위: png (이미 투명 배경이면 그대로, 흰/회색조 배경이 구워져 있으면 자동 투명 처리) →
    gif/webp (움직이는 캐릭터, 투명 배경 네이티브 지원) →
    mp4 (일반 <video> 태그라 투명 배경은 지원 안 됨, 최후의 수단) → 없으면 이모지로 대체.
    """
    assets_dir = Path(__file__).parent / "assets"
    png_path = assets_dir / f"{name}.png"
    gif_path = assets_dir / f"{name}.gif"
    webp_path = assets_dir / f"{name}.webp"
    video_path = assets_dir / f"{name}.mp4"

    with st.container(key=f"mascot_frame_{name}"):
        if png_path.exists():
            if _has_real_transparency(str(png_path)):
                st.image(str(png_path), width=width)
            else:
                cutout = _cutout_white_bg(str(png_path), png_path.stat().st_mtime)
                st.image(cutout, width=width)
        elif gif_path.exists():
            st.image(str(gif_path), width=width)
        elif webp_path.exists():
            st.image(str(webp_path), width=width)
        elif video_path.exists():
            st.video(str(video_path), loop=True, autoplay=True, muted=True, width=width)
        else:
            st.markdown(f'<div style="font-size:{width * 0.55}px; line-height:1;">🛡️</div>', unsafe_allow_html=True)

