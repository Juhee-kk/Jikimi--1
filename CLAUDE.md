# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

든든이 ("Deundeuni") is a Streamlit app (in Korean) that helps users identify and respond to financial
fraud/scams. The intended flow, per the sidebar navigation, is: 홈 (Home) → 상황 진단 (Situation
diagnosis / chat) → 대응 가이드 (Response guide / result).

The project is in an early scaffolding state: most files exist as empty stubs (`main.py`,
`components.py`, `mock_data.py`, `services.py`, and all three files under `pages_files/`) waiting to be
implemented. `app.py` is the current entry point wiring up navigation.

## Environment and commands

There is no `requirements.txt` yet. Dependencies are installed directly into the `venv/` virtualenv
(Python 3.14, Streamlit 1.61.1, plus pandas/numpy/altair/pydeck as transitive Streamlit deps).

Activate the venv and run the app from PowerShell:

```powershell
venv\Scripts\Activate.ps1
streamlit run app.py
```

There are no test, lint, or build scripts configured. `test.py` at the repo root is a second,
redundant navigation entry point, not an automated test suite — do not confuse it with a real test file.

## Architecture

- **`app.py`** — the actual entry point. Calls `st.set_page_config`, builds the sidebar, registers the
  three pages via `st.Page`/`st.navigation`, and adds manual nav buttons (`st.switch_page`) below the
  router as a fallback/duplicate to the sidebar nav.
- **`pages_files/`** — one module per `st.Page` screen (`home.py`, `chat.py`, `result.py`), referenced by
  relative path from `app.py`. Currently empty; page content belongs here.
- **`components.py`** — intended home for shared/reusable Streamlit UI components across pages.
- **`services.py`** — intended home for business logic / external calls (e.g. fraud-checking logic) kept
  out of the page files.
- **`mock_data.py`** — intended home for placeholder/sample data used before real data sources exist.
- **`main.py`** — a near-duplicate of `app.py`'s navigation setup; currently just prints "hi yoo". Not
  wired as the real entry point — prefer `app.py` when adding navigation/routing logic, and reconcile or
  remove `main.py` if it's found to be redundant.

Since `st.Page` targets are passed as relative paths (`"pages_files/home.py"`), always run Streamlit
from the repository root so page navigation resolves correctly.
