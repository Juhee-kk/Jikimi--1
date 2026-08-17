import streamlit as st

from components import inject_custom_css, render_footer, render_top_nav

st.set_page_config(page_title="텅장지키미", page_icon="🛡️", layout="wide")
inject_custom_css()

home = st.Page("pages_files/home.py", title="홈", icon=":material/home:", default=True, url_path="home")
chat = st.Page("pages_files/chat.py", title="상황 진단", icon=":material/chat:", url_path="chat")
news = st.Page("pages_files/news.py", title="요즘 수법", icon=":material/newspaper:", url_path="news")

# 상황 진단(chat)은 홈/카드의 CTA로만 진입 — 상단 탭에는 노출하지 않음
# 퀴즈는 요즘 수법 페이지 안의 내부 탭으로 들어있어 별도 페이지가 아님
all_pages = [home, chat, news]
tab_pages = [home, news]

nav = st.navigation(all_pages, position="hidden")

render_top_nav(tab_pages)
nav.run()
render_footer()
