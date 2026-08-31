# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

텅장지키미 is a Streamlit app (in Korean, targeting 19–34 year olds) that helps users decide whether a
situation they are in is a financial scam, and tells them what to do next.

Three screens, wired in `app.py`:

- **홈** (`pages_files/home.py`) — service intro. Two entry points into the chat: the hero CTA and the
  four situation cards (each card's `chip` string becomes the chatbot's first user message).
- **상황 진단** (`pages_files/chat.py`) — the diagnostic chatbot. Not shown in the top nav; reached only
  via a CTA from 홈 or 요즘 수법.
- **요즘 수법** (`pages_files/news.py`) — police statistics, the 8 fixed scam types, freshly detected
  novel scams from the news pipeline, and the quiz (an in-page section, not a separate `st.Page`).

## Environment and commands

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

`st.Page` targets are relative paths (`"pages_files/home.py"`), so **always run Streamlit from the
repository root**.

Chatbot calls need an Upstage API key. See `.streamlit/secrets.toml.example`; `scam_data_pipeline.get_secret()`
(re-exported as `services.get_secret`) reads `st.secrets` first, then the environment.

`tests/` holds the golden set and evaluation scripts. It is gitignored (local only) — do not delete it.
`run_decision_eval.py` is the authoritative one: it scores `services.py`'s real `decision` output.

## Architecture

Layered so that the page files hold layout only:

- **`app.py`** — entry point. `st.set_page_config`, CSS injection, `st.navigation` (hidden), top nav,
  footer.
- **`pages_files/*.py`** — one module per screen. Each runs top-to-bottom on every rerun. Render helpers
  used by exactly one page live in that page's file (e.g. `render_quiz`, `render_new_scam_card` in
  `news.py`).
- **`components.py`** — only what crosses pages: the global stylesheet, top nav, footer, chat bubbles,
  the mascot renderer, and `queue_chat_prefill()` (the 홈/뉴스 → 챗 handoff via
  `st.session_state["prefill_chip"]`).
- **`content.py`** — every user-visible string, grouped by screen (공통 / 홈 / 상황 진단 / 요즘 수법),
  plus `FRAUD_TYPES` (the 8 fixed scam types, whose `id`s match `data/taxonomy/scam_taxonomy.json` and
  are the aggregation keys for `scam_feed.count_by_category()`).
- **`services.py`** — all chatbot logic: structuring, Qdrant recall, LLM coverage judging, damage-stage
  classification, guide and tool generation. Its module docstring documents the five-step flow.
- **`guide_templates.py`** — hardcoded response guides from counterscam112.go.kr. Real official content,
  not copy — do not edit agency names, URLs, or phone numbers without checking the source.
- **`scam_feed.py`** — turns `data/structured_scam_articles.jsonl` into what 요즘 수법 renders (30-day
  category counts, novel-scam card pool).
- **`scam_data_pipeline.py`** — the collect → structure → index pipeline behind that jsonl. Run on a
  schedule by `.github/workflows/`.

Two things generate text and must not be confused: `content.py` holds fixed copy that a human wrote;
`services.py` + `guide_templates.py` produce per-situation output at runtime.

## Conventions

- Comments and docstrings are in Korean and explain *why*, not what. Match that.
- All user-facing HTML goes through `components.fmt()`, which escapes the text and then allows only
  `**bold**` and newlines. Never interpolate raw user or LLM text into markup.
- Streamlit renders 4-space-indented lines inside `st.markdown` as code blocks. Multi-element HTML is
  therefore built as one joined string, not an indented f-string block.
- Per-page CSS is injected at the top of that page file; only shared rules go in
  `components.inject_custom_css()`.
