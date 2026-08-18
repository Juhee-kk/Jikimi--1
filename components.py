"""텅장지키미 공유 UI 렌더 함수."""

from __future__ import annotations

import html as html_lib
import io
import re
from collections import deque
from pathlib import Path

import streamlit as st
from PIL import Image

import mock_data as data


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
        @import url('https://fonts.googleapis.com/css2?family=Hahmlet:wght@400;500;600;700&family=Noto+Sans+KR:wght@400;500;700&display=swap');

        :root {
            --ink: #16181A; --ink-2: #4A5058; --ink-3: #8A9199;
            --paper: #F4F4F1; --paper-2: #FFFFFF;
            --seal: #C0392B; --mark: #1B3BC7;
            --rule: rgba(22,24,26,0.14); --rule-2: rgba(22,24,26,0.07);
            --dj-primary: #1B3BC7; --dj-primary-dark: #16181A;
            --dj-signal: #1B3BC7; --dj-alert: #C0392B;
            --dj-bg: #F4F4F1; --dj-white: #FFFFFF; --dj-text: #16181A; --dj-muted: #4A5058;
            --dj-card-blue: #ECEEF8; --dj-card-green: #EAEFEC;
            --dj-card-yellow: #F5F1E4; --dj-card-coral: #F7EBE9;
            --dj-border: rgba(22,24,26,0.14);
            --dj-radius-lg: 2px; --dj-radius-pill: 2px;
        }
        html, body, [class*="css"], .stApp, .stMarkdown, p, span, div, li {
            font-family: 'Noto Sans KR', -apple-system, 'Malgun Gothic', sans-serif;
            letter-spacing: -0.012em;
        }
        html, body, .stApp { overflow-x: hidden; }
        .stApp { background-color: var(--paper); color: var(--ink); }
        [data-testid="stHeader"] { background: transparent; height: 0 !important; min-height: 0 !important; }
        [data-testid="stAppViewContainer"] > .main .block-container { max-width: 1000px; padding-top: 0 !important; }
        [data-testid="stMainBlockContainer"] { padding-top: 1.6rem !important; }

        .dj-headline {
            font-family: 'Hahmlet', serif; font-weight: 600; line-height: 1.32;
            letter-spacing: -0.028em; color: var(--ink);
        }
        .dj-fig {
            font-family: 'Hahmlet', serif; font-weight: 600;
            font-variant-numeric: tabular-nums; letter-spacing: -0.02em; line-height: 1;
        }
        .dj-eyebrow {
            font-size: 0.68rem; font-weight: 700; letter-spacing: 0.16em;
            color: var(--ink-3); text-transform: uppercase;
        }
        .dj-section {
            display: flex; align-items: baseline; gap: 0.9rem;
            border-bottom: 2px solid var(--ink); padding-bottom: 0.5rem; margin-bottom: 1.4rem;
        }
        .dj-section .num { font-family:'Hahmlet',serif; font-size:0.9rem; font-weight:700; flex-shrink:0; }
        .dj-section .ttl { font-family:'Hahmlet',serif; font-size:1.3rem; font-weight:600; letter-spacing:-0.03em; }
        .dj-section .meta { margin-left:auto; font-size:0.72rem; color:var(--ink-3); white-space:nowrap; }

        .dj-logo {
            font-family:'Hahmlet',serif; font-weight:700; font-size:1.45rem;
            color:var(--ink); letter-spacing:-0.04em; padding-top:0.35rem;
        }
        [data-testid="stPageLink"] {
            border-radius:0 !important; padding:0.34rem 0 !important;
            background:transparent; border:0; border-bottom:2px solid transparent;
        }
        [data-testid="stPageLink"] p { font-weight:500 !important; font-size:0.86rem !important; color:var(--ink-2) !important; }
        [data-testid="stPageLink"][aria-current="page"] { background:transparent !important; border-bottom:2px solid var(--ink) !important; }
        [data-testid="stPageLink"][aria-current="page"] p { color:var(--ink) !important; font-weight:700 !important; }

        .stButton > button {
            border-radius:2px; font-weight:500; font-size:0.86rem;
            border:1px solid var(--rule); background:var(--paper-2); color:var(--ink);
            padding:0.45rem 1rem; transition:border-color .12s,color .12s;
        }
        .stButton > button:hover { border-color:var(--mark); color:var(--mark); background:var(--paper-2); }
        .stButton > button[kind="primary"] { background:var(--seal); border-color:var(--seal); color:#fff; font-weight:700; }
        .stButton > button[kind="primary"]:hover { background:#A32F22; border-color:#A32F22; color:#fff; }
        .stButton > button:focus-visible { outline:2px solid var(--mark); outline-offset:1px; }
        .stLinkButton > a {
            border-radius:2px !important; border:1px solid var(--rule) !important;
            background:var(--paper-2) !important; color:var(--ink) !important;
            font-weight:500 !important; font-size:0.84rem !important;
        }
        .stLinkButton > a:hover { border-color:var(--mark) !important; color:var(--mark) !important; }

        div[class*="st-key-hero_band"] {
            position:relative; padding:0.6rem 0 2.2rem; text-align:left; border-bottom:2px solid var(--ink);
        }
        div[class*="st-key-hero_band"] .dj-headline { color:var(--ink); }
        div[class*="st-key-hero_band"] .stButton { display:block; }
        div[class*="st-key-hero_band"] .stButton > button {
            background:var(--seal); border-color:var(--seal); color:#fff;
            font-weight:700; font-size:0.95rem; padding:0.62rem 1.6rem;
        }

        .dj-full-bleed {
            position:static; left:auto; right:auto; margin:2.4rem 0 0 !important;
            width:auto; padding:1.8rem 0 0; text-align:left; border-top:2px solid var(--ink);
        }
        .dj-full-bleed-inner { max-width:none; margin:0; }
        .dj-full-bleed.dj-dark { background:transparent; color:var(--ink); }
        .dj-full-bleed.dj-dark .dj-headline { color:var(--ink); }
        .dj-full-bleed.dj-footer-band { background:transparent; color:var(--ink-2); padding-top:1.6rem; }
        .dj-full-bleed.dj-footer-band .dj-headline { color:var(--ink); }

        div[class*="st-key-mascot_frame"] { display:flex; align-items:center; justify-content:flex-start; min-height:0; }
        div[class*="st-key-mascot_frame"] img { filter:none; }

        .dj-card { border-radius:2px; padding:1.1rem 0 0; height:100%; box-shadow:none;
                   background:transparent; border-top:1px solid var(--rule); }
        .dj-card-white, .dj-card-coral-tint, .dj-card-blue, .dj-card-green, .dj-card-yellow, .dj-card-coral {
            background:transparent; border:0; border-top:1px solid var(--rule);
        }
        .dj-card-dark { background:var(--ink); color:var(--paper); padding:1.2rem 1.4rem; border:0; }
        .dj-card-dark .dj-headline { color:var(--paper); }
        .dj-step-1,.dj-step-2,.dj-step-3,.dj-step-4 {
            background:transparent; color:var(--ink); border:0; border-top:3px solid var(--ink); padding:0.9rem 0 0;
        }
        .dj-step-1 { border-top-color:var(--mark); }
        .dj-step-2 { border-top-color:#2F6152; }
        .dj-step-3 { border-top-color:#8A6A1E; }
        .dj-step-4 { border-top-color:var(--seal); }

        .dj-badge { display:inline-block; padding:0.16rem 0.5rem; border-radius:2px;
                    font-weight:700; font-size:0.7rem; border:1px solid var(--rule);
                    background:var(--paper-2); color:var(--ink-2); }

        .dj-chat-row { display:block; margin-bottom:1.05rem; }
        .dj-bubble { max-width:100%; border-radius:0; font-size:0.93rem; line-height:1.72;
                     padding:0 0 0 0.95rem; background:transparent !important; border:0 !important; }
        .dj-bubble.assistant { border-left:2px solid var(--ink) !important; color:var(--ink); }
        .dj-bubble.user { border-left:2px solid var(--rule) !important; color:var(--ink-2); }

        /* 시간축: 버튼을 눈금처럼 */
        div[class*="st-key-tl_axis"] .stButton > button {
            border:0 !important; background:transparent !important;
            padding:0.15rem 0 0.5rem !important; text-align:left !important;
            justify-content:flex-start !important;
            font-size:0.7rem !important; font-weight:500 !important;
            color:var(--ink-3) !important; letter-spacing:0 !important;
        }
        div[class*="st-key-tl_axis"] .stButton > button:hover { color:var(--mark) !important; }
        div[class*="st-key-tl_axis"] .stButton > button p { font-size:0.7rem !important; }

        /* 접힌 단계 줄 */
        div[class*="st-key-tl_row_"] .stButton > button {
            border:0 !important; border-top:1px solid var(--rule) !important;
            border-radius:0 !important; background:transparent !important;
            padding:0.72rem 0 !important; text-align:left !important;
            justify-content:flex-start !important;
            font-weight:500 !important; color:var(--ink-2) !important;
        }
        div[class*="st-key-tl_row_"] .stButton > button:hover {
            color:var(--ink) !important; background:rgba(22,24,26,0.03) !important;
        }
        div[class*="st-key-tl_row_"] .stButton > button p {
            font-size:0.88rem !important; white-space:pre !important;
        }

        .dj-script { border-left:2px solid var(--mark); padding:0.15rem 0 0.15rem 1rem;
                     font-size:0.9rem; line-height:1.85; white-space:pre-line; color:var(--ink); }

        .stExpander { border:0 !important; border-top:1px solid var(--rule-2) !important;
                      border-radius:0 !important; background:transparent !important; }
        .stExpander summary { font-size:0.82rem !important; font-weight:500 !important; }
        [data-testid="stExpander"] details { border:0 !important; background:transparent !important; }

        div[class*="st-key-quiz_box"] { background:transparent; border:0; border-top:2px solid var(--ink); padding:1.4rem 0 0; }
        div[class*="st-key-news_card_"] { display:flex; flex-direction:column; height:100%; margin-bottom:1.1rem; }
        div[class*="st-key-news_card_"] .dj-card { padding-top:0.9rem; flex:1; }
        div[class*="st-key-entry_card_"] .stButton > button { color:var(--ink); }

        .dj-footer { margin-top:2.4rem; padding:1.1rem 0 2rem; border-top:1px solid var(--rule);
                     font-size:0.75rem; color:var(--ink-3); text-align:left; line-height:1.7; }
        a { color:var(--mark); }
        code, .stCode { border-radius:2px !important; }
        hr { border-color:var(--rule); }
        ::selection { background:rgba(27,59,199,0.16); }
        @media (prefers-reduced-motion: reduce) { * { transition:none !important; animation:none !important; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# 레이아웃 조각
# ---------------------------------------------------------------------------

def render_top_nav(pages: list) -> None:
    logo_col, *nav_cols = st.columns([3] + [1] * len(pages))
    with logo_col:
        st.markdown('<div class="dj-logo">🛡️ 텅장지키미</div>', unsafe_allow_html=True)
    for col, page in zip(nav_cols, pages):
        with col:
            st.page_link(page, use_container_width=True)


def render_footer() -> None:
    st.markdown(f'<div class="dj-footer">{fmt(data.FOOTER_TEXT)}</div>', unsafe_allow_html=True)


def render_dark_band(title: str, steps: list[dict]) -> None:
    """딥그린 풀블리드 3단계 섹션."""
    step_colors = ["var(--dj-card-coral)", "var(--dj-card-blue)", "var(--dj-card-green)"]
    steps_html = "".join(
        f'''
        <div style="flex:1; min-width:150px;">
            <div style="width:56px; height:56px; border-radius:50%; background:{color};
                        display:flex; align-items:center; justify-content:center;
                        font-weight:700; font-size:1.3rem; margin:0 auto; color: var(--dj-text);">{step["num"]}</div>
            <div style="font-weight:700; margin-top:0.7rem;">{fmt(step["title"])}</div>
            <div style="font-size:0.85rem; margin-top:0.3rem; opacity:0.8;">{fmt(step["desc"])}</div>
        </div>
        '''
        for step, color in zip(steps, step_colors)
    )
    st.markdown(
        f'''
        <div class="dj-full-bleed dj-dark"><div class="dj-full-bleed-inner">
            <div class="dj-headline" style="font-size:1.5rem; margin-bottom:1.8rem;">{fmt(title)}</div>
            <div style="display:flex; gap:1.5rem; flex-wrap:wrap; justify-content:center;">{steps_html}</div>
        </div></div>
        ''',
        unsafe_allow_html=True,
    )


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
# 카드류
# ---------------------------------------------------------------------------

def risk_badge_html(level: str) -> str:
    info = data.RISK_LEVELS[level]
    return (
        f'<span class="dj-badge" style="background:{info["bg"]};color:{info["color"]}">'
        f'{info["emoji"]} {info["label"]}</span>'
    )


def render_risk_result(result) -> None:
    """services.DiagnosisResult를 카드로 렌더."""
    info = data.RISK_LEVELS[result.level]
    st.markdown(
        f'''
        <div class="dj-card dj-card-white" style="border-left: 6px solid {info["color"]}">
            {risk_badge_html(result.level)}
            <div class="dj-headline" style="font-size:1.3rem; margin-top:0.6rem;">{fmt(result.headline)}</div>
            <div style="margin-top:0.5rem;">{fmt(result.body)}</div>
        </div>
        ''',
        unsafe_allow_html=True,
    )
    if result.evidence:
        with st.container():
            st.markdown("**왜 이렇게 봤냐면요**")
            for ev in result.evidence:
                st.markdown(
                    f'''
                    <div class="dj-card dj-card-white" style="margin-bottom:0.6rem;">
                        🔎 {fmt(ev["quote"])}<br>
                        <span style="color: var(--dj-primary-dark); font-weight:600;">→ {fmt(ev["explain"])}</span><br>
                        <span style="font-size:0.8rem; opacity:0.7;">📄 근거: {fmt(ev["source"])}</span>
                    </div>
                    ''',
                    unsafe_allow_html=True,
                )


def render_fraud_type_card(type_dict: dict, highlight: bool = False, anchor: str | None = None) -> None:
    if anchor:
        st.markdown(f'<div id="{anchor}"></div>', unsafe_allow_html=True)
    top = "3px solid var(--ink)" if highlight else "1px solid var(--rule)"
    flags = "".join(f'''<div style="display:flex; gap:0.5rem; padding:0.16rem 0;">
        <span style="color:var(--ink-3); flex-shrink:0;">·</span><span>{fmt(r)}</span></div>'''
        for r in type_dict["red_flags"])
    acts = "".join(f'''<div style="display:flex; gap:0.55rem; padding:0.16rem 0;">
        <span class="dj-fig" style="font-size:0.76rem; color:var(--ink-3); flex-shrink:0;
        padding-top:0.15rem;">{i}</span><span>{fmt(a)}</span></div>'''
        for i, a in enumerate(type_dict["actions"], 1))
    badge = ""
    if "refund" in type_dict:
        b = data.REFUND_BADGE[type_dict["refund"]]
        badge = (f'<span style="font-size:0.67rem; font-weight:700; color:{b["color"]}; '
                 f'border:1px solid {b["color"]}44; padding:0.1rem 0.42rem;">{b["text"]}</span>')
    warn = (f'''<div style="margin-top:0.7rem; padding-top:0.6rem; border-top:1px solid var(--rule-2);
        font-size:0.8rem; color:var(--ink-2); line-height:1.7;">{fmt(type_dict["warning"])}</div>'''
        if type_dict.get("warning") else "")
    st.markdown(f'''<div style="border-top:{top}; padding:0.85rem 0 1.6rem;">
        <div style="display:flex; align-items:flex-start; gap:0.55rem;">
            <span style="flex-shrink:0; padding-top:0.15rem;">{fraud_icon(type_dict["id"])}</span>
            <span class="dj-headline" style="font-size:1.01rem;">{fmt(type_dict["title"])}</span></div>
        <div style="margin-top:0.4rem;">{badge}</div>
        <div style="font-size:0.85rem; line-height:1.72; margin-top:0.6rem;">{fmt(type_dict["situation"])}</div>
        <div class="dj-eyebrow" style="margin-top:0.9rem; display:block;">이 말 나오면</div>
        <div style="font-size:0.83rem; line-height:1.68; margin-top:0.3rem; color:var(--ink-2);">{flags}</div>
        <div class="dj-eyebrow" style="margin-top:0.9rem; display:block;">지금 할 일</div>
        <div style="font-size:0.83rem; line-height:1.68; margin-top:0.3rem;">{acts}</div>
        {warn}</div>''', unsafe_allow_html=True)


def render_monthly_stats(stats: dict) -> None:
    figs = [
        (f'{stats["total_cases"]:,}', "건", "이번 달 발생", f'{stats["vs_prev_label"]} {stats["vs_prev"]}'),
        (stats["total_amount"], "", "이번 달 피해액", ""),
        (stats["youth_share"], "", "기관사칭 피해자 중 20·30대", ""),
        (stats["top_amount"], "", "기관사칭 1건당 평균", ""),
    ]
    cells = ""
    for i, (val, unit, label, delta) in enumerate(figs):
        border = "" if i == 0 else "border-left:1px solid var(--rule);"
        d = f'<div style="font-size:0.7rem; color:var(--ink-2); margin-top:0.2rem;">{delta}</div>' if delta else ""
        cells += f'''<div style="flex:1; min-width:118px; padding:0 1.1rem; {border}">
            <div class="dj-fig" style="font-size:2rem;">{val}<span style="font-size:0.85rem; font-weight:500;">{unit}</span></div>
            {d}<div style="font-size:0.72rem; color:var(--ink-3); margin-top:0.45rem; line-height:1.45;">{label}</div>
        </div>'''
    total = sum(t["cases"] for t in stats["by_type"]) or 1
    rows = ""
    for t in stats["by_type"]:
        pct = t["cases"] / total * 100
        rows += f'''<tr>
            <td style="padding:0.5rem 0; border-bottom:1px solid var(--rule-2); font-size:0.85rem;">{t["name"]}</td>
            <td style="padding:0.5rem 0; border-bottom:1px solid var(--rule-2); width:46%;">
                <div style="height:6px; background:var(--rule-2);"><div style="width:{pct:.0f}%; height:100%; background:var(--ink);"></div></div></td>
            <td class="dj-fig" style="padding:0.5rem 0 0.5rem 1rem; border-bottom:1px solid var(--rule-2);
                text-align:right; font-size:0.95rem; white-space:nowrap;">{t["cases"]:,}{t["unit"]}</td></tr>'''
    st.markdown(f'''<div style="border-top:2px solid var(--ink); padding-top:1.1rem;">
        <div style="display:flex; flex-wrap:wrap; margin-left:-1.1rem;">{cells}</div>
        <div style="margin-top:1.6rem; padding-top:1.1rem; border-top:1px solid var(--rule);">
            <div class="dj-eyebrow">{stats["by_type_note"]}</div>
            <table style="width:100%; border-collapse:collapse; margin-top:0.6rem;">{rows}</table>
            <div style="font-size:0.68rem; color:var(--ink-3); margin-top:0.7rem;">{stats["source"]}</div>
        </div></div>''', unsafe_allow_html=True)


def render_new_scam_alerts(alerts: list[dict], intro: str = "") -> None:
    st.markdown(f'''<div class="dj-section"><span class="num">02</span>
        <span class="ttl">아직 이름도 없는 수법</span>
        <span class="meta">분류 미등록 {len(alerts)}건</span></div>''', unsafe_allow_html=True)
    if intro:
        st.markdown(f'''<div style="font-size:0.86rem; color:var(--ink-2); line-height:1.75;
            margin:-0.7rem 0 1.5rem; max-width:62ch;">{fmt(intro)}</div>''', unsafe_allow_html=True)
    for i, a in enumerate(alerts, 1):
        tag = "var(--seal)" if a["detected"] == "이번 달 신규" else "var(--ink-3)"
        st.markdown(f'''<div style="display:flex; gap:1.4rem; padding:1.1rem 0; border-top:1px solid var(--rule-2);">
            <div style="flex-shrink:0; width:2.2rem;"><div class="dj-fig" style="font-size:1.1rem; color:var(--ink-3);">{i:02d}</div></div>
            <div style="flex:1;">
                <div style="display:flex; align-items:baseline; gap:0.7rem; flex-wrap:wrap;">
                    <span class="dj-headline" style="font-size:1.02rem;">{fmt(a["title"])}</span>
                    <span style="font-size:0.68rem; font-weight:700; color:{tag}; letter-spacing:0.06em;">{a["detected"]}</span></div>
                <div style="font-size:0.88rem; line-height:1.78; margin-top:0.45rem; max-width:62ch;">{fmt(a["body"])}</div>
                <div style="font-size:0.8rem; color:var(--ink-2); line-height:1.7; margin-top:0.6rem;
                     padding-left:0.9rem; border-left:2px solid var(--rule); max-width:62ch;">
                    <span class="dj-eyebrow">왜 못 걸러지나</span><br>{fmt(a["why_new"])}</div>
            </div></div>''', unsafe_allow_html=True)


def render_agency_section(phones: list[dict], onlines: list[dict], banks: list[tuple]) -> None:
    st.markdown('''<div class="dj-section"><span class="num">04</span>
        <span class="ttl">어디에 연락하나</span><span class="meta">모르겠으면 112</span></div>''', unsafe_allow_html=True)
    rows = ""
    for p in phones:
        w = "700" if p["urgent"] else "500"
        c = "var(--seal)" if p["urgent"] else "var(--ink)"
        rows += f'''<tr>
            <td style="padding:0.62rem 0; border-bottom:1px solid var(--rule-2); font-size:0.87rem;">{p["name"]}</td>
            <td class="dj-fig" style="padding:0.62rem 0; border-bottom:1px solid var(--rule-2); text-align:right;
                font-size:1.08rem; font-weight:{w}; color:{c}; white-space:nowrap;">{p["phone"]}</td></tr>
            <tr><td colspan="2" style="padding:0 0 0.5rem; font-size:0.74rem; color:var(--ink-3);">{p["when"]}</td></tr>'''
    orows = ""
    for o in onlines:
        orows += f'''<tr><td style="padding:0.62rem 0; border-bottom:1px solid var(--rule-2);">
            <a href="{o["url"]}" target="_blank" style="font-size:0.85rem; font-weight:500; text-decoration:none;">{o["site"]}</a>
            <div style="font-size:0.74rem; color:var(--ink-3); margin-top:0.12rem;">{o["when"]}</div></td></tr>'''
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown(f'''<div class="dj-eyebrow">전화</div>
            <table style="width:100%; border-collapse:collapse; margin-top:0.5rem;">{rows}</table>''', unsafe_allow_html=True)
    with right:
        st.markdown(f'''<div class="dj-eyebrow">온라인</div>
            <table style="width:100%; border-collapse:collapse; margin-top:0.5rem;">{orows}</table>''', unsafe_allow_html=True)
    cells = "".join(
        f'''<td style="padding:0.45rem 1rem 0.45rem 0; font-size:0.8rem; white-space:nowrap;">{n}
            <span class="dj-fig" style="font-size:0.85rem;">{ph}</span></td>''' + ("</tr><tr>" if i % 4 == 3 else "")
        for i, (n, ph) in enumerate(banks))
    st.markdown(f'''<div style="margin-top:1.6rem; padding-top:1rem; border-top:1px solid var(--rule);">
        <div class="dj-eyebrow">은행 고객센터</div>
        <table style="border-collapse:collapse; margin-top:0.4rem;"><tr>{cells}</tr></table></div>''', unsafe_allow_html=True)


def render_timeline(steps: list[dict]) -> None:
    for step in steps:
        st.markdown(
            f'''
            <div class="dj-timeline-item">
                <div class="dj-timeline-dot" style="background:{step["color"]}"></div>
                <div>
                    <div style="font-weight:700;">{step["time"]} · {step["label"]}</div>
                    <div style="margin-top:0.25rem;">{fmt(step["task"])}</div>
                    <div style="margin-top:0.25rem; font-size:0.85rem; opacity:0.7;">왜 지금? {fmt(step["why"])}</div>
                </div>
            </div>
            ''',
            unsafe_allow_html=True,
        )


def render_response_timeline(steps: list[dict], intro: str = "") -> None:
    """대응 순서 — 클릭 가능한 시간축 + 선택 단계만 펼침."""
    st.markdown('''<div class="dj-section"><span class="num">03</span>
        <span class="ttl">돈 보낸 순간부터 시계가 돌아간다</span>
        <span class="meta">위에서부터 순서대로</span></div>''', unsafe_allow_html=True)
    if intro:
        st.markdown(f'''<div style="font-size:0.86rem; color:var(--ink-2); line-height:1.75;
            margin:-0.7rem 0 1.4rem; max-width:60ch;">{fmt(intro)}</div>''', unsafe_allow_html=True)

    st.session_state.setdefault("tl_active", 1)
    active = st.session_state.tl_active
    total = len(steps)

    # ── 시간축: 눌러서 이동 ──
    with st.container(key="tl_axis"):
        cols = st.columns(total, gap="small")
        for col, s in zip(cols, steps):
            on = s["no"] == active
            with col:
                st.markdown(
                    f'''<div style="border-top:{"3px" if on else "1px"} solid
                        {"var(--seal)" if on else "var(--rule)"}; padding-top:0.4rem;"></div>''',
                    unsafe_allow_html=True,
                )
                if st.button(s["time"], key=f"tl_seg_{s['no']}", use_container_width=True):
                    st.session_state.tl_active = s["no"]
                    st.rerun()

    st.markdown("<div style='height:1.3rem'></div>", unsafe_allow_html=True)

    # ── 단계 목록 ──
    for step in steps:
        on = step["no"] == active
        urgent = step["no"] == 1
        accent = "var(--seal)" if urgent else "var(--ink)"

        if not on:
            # 접힌 줄 — 눌러서 펼침
            with st.container(key=f"tl_row_{step['no']}"):
                if st.button(
                    f"{step['no']}   {step['time']}   {step['label']}",
                    key=f"tl_open_{step['no']}", use_container_width=True,
                ):
                    st.session_state.tl_active = step["no"]
                    st.rerun()
            continue

        no_col, body_col = st.columns([0.055, 0.945], gap="small")
        with no_col:
            st.markdown(f'''<div class="dj-fig" style="font-size:1.55rem; color:{accent};
                padding-top:0.5rem;">{step["no"]}</div>''', unsafe_allow_html=True)
        with body_col:
            tasks = "".join(f'''<div style="display:flex; gap:0.6rem; padding:0.24rem 0;
                font-size:0.94rem; line-height:1.7;"><span style="color:var(--ink-3); flex-shrink:0;">—</span>
                <span>{fmt(t)}</span></div>''' for t in step["tasks"])
            st.markdown(f'''<div style="border-top:2px solid {accent}; padding:0.75rem 0 0;">
                <div style="display:flex; align-items:baseline; gap:0.8rem; flex-wrap:wrap;">
                    <span class="dj-eyebrow" style="color:{accent};">{step["time"]}</span>
                    <span class="dj-headline" style="font-size:1.18rem;">{fmt(step["label"])}</span>
                    <span style="margin-left:auto; font-size:0.72rem; color:var(--ink-3);">
                        {step["no"]} / {total}</span></div>
                <div style="margin-top:0.6rem; max-width:64ch;">{tasks}</div>
                <div style="margin-top:0.7rem; font-size:0.82rem; color:var(--ink-2); line-height:1.72; max-width:64ch;">
                    <span class="dj-eyebrow">왜 지금</span>&nbsp; {fmt(step["why"])}</div>
                <div style="margin-top:0.35rem; font-size:0.8rem; color:var(--ink-3); line-height:1.72;
                     max-width:64ch;">{fmt(step["tip"])}</div></div>''', unsafe_allow_html=True)

            if step["links"]:
                lcols = st.columns(min(len(step["links"]) + 1, 3))
                for lc, link in zip(lcols, step["links"]):
                    with lc:
                        st.link_button(link["label"], link["url"], use_container_width=True)

            with st.expander(f'통화 대본 · {step["script_title"]}'):
                st.markdown(f'''<div class="dj-script">{fmt(step["script"])}</div>
                    <div style="font-size:0.76rem; color:var(--ink-3); margin-top:0.7rem;
                    line-height:1.7;">{fmt(step["script_note"])}</div>''', unsafe_allow_html=True)
                st.code(step["script"], language=None)

            nav_prev, nav_next, _ = st.columns([1, 1, 2.4])
            with nav_prev:
                if step["no"] > 1 and st.button("← 이전", key=f"tl_prev_{step['no']}",
                                                use_container_width=True):
                    st.session_state.tl_active = step["no"] - 1
                    st.rerun()
            with nav_next:
                if step["no"] < total and st.button("다음 단계 →", key=f"tl_next_{step['no']}",
                                                    use_container_width=True):
                    st.session_state.tl_active = step["no"] + 1
                    st.rerun()

        st.markdown("<div style='height:0.9rem'></div>", unsafe_allow_html=True)


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

    # 이미 알파 채널이 제대로 있는 파일이면 손대지 않는다.
    # (검은 선화는 그 자체가 무채색이라 아래 flood fill에 지워질 수 있음)
    alpha = img.getchannel("A")
    corners = [alpha.getpixel(pt) for pt in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    if max(corners) < 10:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

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


FRAUD_ICONS: dict[str, str] = {
    "voice_phishing": '<path d="M5 4h4l2 5-2.5 1.5a11 11 0 005 5L15 13l5 2v4a1 1 0 01-1 1A15 15 0 014 5a1 1 0 011-1z"/>',
    "smishing": '<path d="M3 6h18v10H8l-5 4z"/><path d="M8 10h8M8 13h5"/>',
    "messenger_impersonation": '<path d="M12 3a9 9 0 019 9 9 9 0 01-9 9H3l2.5-3.5A9 9 0 0112 3z"/><path d="M9 12h.01M12 12h.01M15 12h.01"/>',
    "romance_scam": '<path d="M12 20s-7-4.4-7-9.4A3.8 3.8 0 0112 8a3.8 3.8 0 017 2.6c0 5-7 9.4-7 9.4z"/>',
    "investment_scam": '<path d="M3 17l5-6 4 3 5-7"/><path d="M17 7h4v4"/><path d="M3 21h18"/>',
    "secondhand_scam": '<path d="M4 5h2l2.2 10h9.4L20 8H7"/><circle cx="10" cy="19" r="1.4"/><circle cx="17" cy="19" r="1.4"/>',
    "part_time_scam": '<rect x="3" y="7" width="18" height="13" rx="1"/><path d="M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2"/><path d="M3 12h18"/>',
    "task_scam": '<path d="M4 5h16v12H4z"/><path d="M8 10l2.5 2.5L16 8"/><path d="M9 21h6"/><path d="M12 17v4"/>',
    "account_takeover": '<rect x="5" y="10" width="14" height="10" rx="1"/><path d="M8 10V7a4 4 0 018 0v3"/><path d="M12 14v2"/>',
}


def fraud_icon(type_id: str, size: int = 22, color: str = "var(--ink)") -> str:
    """유형별 단색 선 아이콘. 굵기·크기 통일."""
    path = FRAUD_ICONS.get(type_id)
    if not path:
        return ""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="1.6" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{path}</svg>'
    )


def render_mascot(width: int = 260, mood: str = "calm", key: str | None = None) -> None:
    """assets/ 폴더의 마스코트 파일을 보여줌.

    우선순위: png (투명 배경 확정, 흰 배경이면 자동 투명 처리) →
    gif/webp (움직이는 캐릭터, 투명 배경 네이티브 지원) →
    mp4 (일반 <video> 태그라 투명 배경은 지원 안 됨, 최후의 수단) → 없으면 이모지로 대체.
    """
    assets_dir = Path(__file__).parent / "assets"
    png_path = assets_dir / f"mascot_{mood}.png"
    if not png_path.exists():
        png_path = assets_dir / "mascot.png"
    gif_path = assets_dir / "mascot.gif"
    webp_path = assets_dir / "mascot.webp"
    video_path = assets_dir / "mascot.mp4"

    frame_key = f"mascot_frame_{key or mood}"
    with st.container(key=frame_key):
        if png_path.exists():
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


def render_quiz() -> None:
    """금융사기 상식 퀴즈 (요즘 수법 페이지의 내부 탭에서 호출)."""
    st.session_state.setdefault("quiz_best_score", None)
    st.session_state.setdefault("quiz_attempts", 0)

    st.caption("하루 3문제. 알고 있으면 안 당해요.")

    with st.form("quiz_form"):
        for i, q in enumerate(data.QUIZ_QUESTIONS):
            st.markdown(f"**문제 {i + 1}.** {q['question']}")
            st.radio("보기", q["options"], key=f"quiz_{i}", index=None, label_visibility="collapsed")
        submitted = st.form_submit_button("도전! (1분이면 끝나요)")

    if submitted:
        score = 0
        for i, q in enumerate(data.QUIZ_QUESTIONS):
            chosen = st.session_state.get(f"quiz_{i}")
            correct_text = q["options"][q["answer"]]
            is_correct = chosen == correct_text
            score += int(is_correct)
            with st.expander(f'{"✅" if is_correct else "❌"} 문제 {i + 1} 해설', expanded=not is_correct):
                st.markdown(fmt(q["explanation"]), unsafe_allow_html=True)

        st.session_state.quiz_attempts += 1
        st.session_state.quiz_last_score = score
        if st.session_state.quiz_best_score is None or score > st.session_state.quiz_best_score:
            st.session_state.quiz_best_score = score

        band = next(b for b in data.QUIZ_RESULT_BANDS if b["min"] <= score <= b["max"])
        st.markdown(
            f'''
            <div class="dj-card dj-card-coral" style="text-align:center; margin-top:1rem;">
                <div style="font-size:1.5rem; font-weight:700;">{band["badge"]}</div>
                <div style="margin-top:0.4rem;">{score}/{len(data.QUIZ_QUESTIONS)} · {band["message"]}</div>
            </div>
            ''',
            unsafe_allow_html=True,
        )
        share_col, ask_col = st.columns(2)
        with share_col:
            if st.button(data.QUIZ_SHARE_LABEL, use_container_width=True):
                st.toast("공유 링크를 복사했어요! (데모)")
        with ask_col:
            if st.button("혹시 지금 겪고 있는 일이 있어요? 바로 물어보기 →", use_container_width=True):
                st.switch_page("pages_files/chat.py")