# 텅장지키미 채팅 파이프라인 구현 명세

> 이 문서는 pages\_files/chat.py 와 services.py 를 수정해서 "사기 의심 진단 → 피해 단계 진단 → 대응 가이드 → 대응 도구" 워크플로우를 실제 LLM(Upstage Solar Pro) 기반으로 동작하게 만들기 위한 명세다. 기존 UI 스타일(components.py의 CSS·컴포넌트)은 유지하고, 로직만 교체한다.

---

## 0\. 전체 흐름 (상태 머신)

phase 상태값: `suspicion` → `damage_stage` → `guided`

사용자 입력

 → \[suspicion\] LLM 분류: 사기 의심 여부

     ├ 근거부족  → 추가 질문 1개 출력 (최대 2회, 초과 시 현재 정보로 강제 판정)

     ├ 낮음     → 안심 안내 \+ "개인정보/입금/링크 요구가 생기면 다시 확인" 문구. phase 유지

     └ 의심     → phase \= damage\_stage 로 전환, 같은 턴에 이어서 피해 단계 분류 실행

 → \[damage\_stage\] LLM 분류: 피해 단계

     ├ 근거부족  → 추가 질문 1개 출력 (최대 2회)

     └ 4단계 중 하나 판정 → 해당 대응 가이드 출력, phase \= guided

 → \[guided\] 대응 도구 버튼 3개 노출

     \[📞 신고 전화 대본\] \[📋 피해 상황 요약 리포트\] \[🗂 증거 보존 체크리스트\]

     버튼 클릭 시에만 해당 도구를 LLM으로 생성 (자동 생성 금지 — 사용자가 선택)

### session\_state 키

st.session\_state.chat\_phase      \# "suspicion" | "damage\_stage" | "guided"

st.session\_state.chat\_messages   \# \[{"role": "user"|"assistant", "content": str}, ...\]

st.session\_state.ask\_count       \# {"suspicion": 0, "damage\_stage": 0}

st.session\_state.damage\_stage    \# 판정된 피해 단계 (guided 진입 후 도구 생성에 사용)

st.session\_state.signals         \# 지금까지 감지된 위험 신호 리스트 (누적)

리셋 버튼(새 상담 시작)을 채팅 상단이나 하단에 하나 둘 것. 누르면 위 키 전부 초기화.

---

## 1\. LLM 호출 — services.py

### 1-1. API 클라이언트

Upstage Solar API. OpenAI 호환 chat completions 형식.

import requests, streamlit as st

UPSTAGE\_URL \= "https://api.upstage.ai/v1/chat/completions"  \# 콘솔 공식 예시로 확인 완료

MODEL \= "solar-pro4"

\# 참고: 콘솔 공식 예시("Chat with Reasoning")는 reasoning\_effort="medium" 파라미터를

\# 함께 씀 (solar-pro4가 추론 모델이라 지원하는 것으로 보임). 아래 call\_llm에는 넣지 않았음 —

\# 우선 없이 테스트하고, JSON 분류 응답이 불안정하면 payload에 "reasoning\_effort": "low"를

\# 추가해서 재시도해볼 것 (추론 단계가 길어지면 응답 속도가 느려질 수 있음).

def call\_llm(system: str, messages: list\[dict\], temperature: float \= 0.3) \-\> str:

    api\_key \= st.secrets\["UPSTAGE\_API\_KEY"\]

    payload \= {

        "model": MODEL,

        "messages": \[{"role": "system", "content": system}\] \+ messages,

        "temperature": temperature,

    }

    r \= requests.post(

        UPSTAGE\_URL,

        headers={"Authorization": f"Bearer {api\_key}"},

        json=payload,

        timeout=30,

    )

    r.raise\_for\_status()

    return r.json()\["choices"\]\[0\]\["message"\]\["content"\]

⚠️ 모델명은 콘솔 API Reference에서 `solar-pro4` 문자열로 확인 완료. 코드값과 일치.

✅ 엔드포인트 URL도 콘솔 Getting Started 페이지(공식 코드 예시)에서 확인 완료: `https://api.upstage.ai/v1/chat/completions` — 코드값과 일치. 추가 확인 불필요.

첫 호출 시 404/400(model not found) 오류가 나면 모델 문자열 표기를, 401/403 오류가 나면 API 키 또는 헤더 형식(Authorization: Bearer ...)을 의심할 것.

### 1-2. JSON 강제 \+ 안전 파싱

분류 호출은 응답을 JSON으로 강제하고, 파싱 실패 시 무조건 "근거부족"으로 폴백한다. (판정 실패가 오판보다 낫다.)

import json, re

def parse\_json\_safe(text: str, fallback: dict) \-\> dict:

    m \= re.search(r"\\{.\*\\}", text, re.DOTALL)  \# 응답에서 첫 { ... } 블록만 추출

    if not m:

        return fallback

    try:

        return json.loads(m.group())

    except json.JSONDecodeError:

        return fallback

### 1-3. 분류 함수 ① — 사기 의심 여부

SUSPICION\_SYSTEM \= """당신은 금융사기 위험 신호를 분석하는 보조 도구다.

사용자가 겪고 있는 상황 설명을 읽고 아래 JSON만 출력하라. 다른 텍스트 금지.

{"label": "의심" | "낮음" | "근거부족",

 "confidence": 0\~100 정수,

 "signals": \["감지된 위험 신호를 짧은 한국어 구로"\],

 "follow\_up": "근거부족일 때 사용자에게 물어볼 질문 1개 (다른 label이면 빈 문자열)"}

판정 기준:

\- "의심": 다음 신호가 하나라도 명확하면. 선입금·보증금 요구 / 개인정보·신분증·계좌 요구 /

  수사기관·금융기관 사칭 정황 / 비밀 유지 강요 / 외부 메신저(텔레그램 등) 이동 유도 /

  출금 거부·추가 입금 요구 / 검증 불가한 고수익 약속 / 앱 설치 유도

\- "낮음": 상황이 충분히 설명됐고 위 신호가 없으면

\- "근거부족": 정보가 부족해 판단할 수 없으면. follow\_up에는 판단에 가장 결정적인

  것 하나만 질문 (예: "혹시 상대방이 돈이나 개인정보를 요구한 적 있나요?")

절대 규칙: "사기가 확실하다"는 단정 금지. signals는 관찰된 사실만 기술."""

def classify\_suspicion(chat\_messages: list\[dict\]) \-\> dict:

    fallback \= {"label": "근거부족", "confidence": 0, "signals": \[\],

                "follow\_up": "상황을 조금 더 자세히 알려주실 수 있나요? 상대방이 뭐라고 했는지, 어떤 요구를 받았는지 궁금해요."}

    raw \= call\_llm(SUSPICION\_SYSTEM, chat\_messages)

    result \= parse\_json\_safe(raw, fallback)

    if result.get("label") not in ("의심", "낮음", "근거부족"):

        return fallback

    return result

### 1-4. 분류 함수 ② — 피해 단계

STAGE\_SYSTEM \= """당신은 금융사기 피해 진행 단계를 분류하는 보조 도구다.

대화를 읽고 아래 JSON만 출력하라. 다른 텍스트 금지.

{"stage": "접촉초기" | "개인정보제공" | "링크클릭앱설치" | "입금송금" | "근거부족",

 "follow\_up": "근거부족일 때 물어볼 질문 1개 (아니면 빈 문자열)"}

단계 정의 (해당되는 가장 진행된 단계 하나를 고른다):

\- "입금송금": 이미 돈을 보냈거나 이체·환전을 완료함 → 가장 우선 판정

\- "링크클릭앱설치": 링크를 눌렀거나 앱·프로그램을 설치함 (돈은 아직 안 보냄)

\- "개인정보제공": 신분증·계좌번호·비밀번호 등 개인정보를 넘김 (링크/입금은 아직)

\- "접촉초기": 연락만 받았고 아직 아무것도 제공하지 않음

\- "근거부족": 위를 판단할 정보가 없음. follow\_up 예:

  "혹시 지금까지 돈을 보내거나, 링크를 누르거나, 개인정보를 알려준 적이 있나요?"

"""

def classify\_damage\_stage(chat\_messages: list\[dict\]) \-\> dict:

    fallback \= {"stage": "근거부족",

                "follow\_up": "혹시 지금까지 돈을 보내거나, 링크를 누르거나, 개인정보를 알려주신 적이 있나요?"}

    raw \= call\_llm(STAGE\_SYSTEM, chat\_messages)

    result \= parse\_json\_safe(raw, fallback)

    if result.get("stage") not in ("접촉초기", "개인정보제공", "링크클릭앱설치", "입금송금", "근거부족"):

        return fallback

    return result

---

## 2\. 대응 가이드 4종 — 혼합 방식 (고정 뼈대 \+ LLM 개인화)

원칙: **행동 지침·기관명·연락처는 고정 템플릿** (LLM이 지어내면 위험), **공감 문구와 상황 요약만 LLM 생성**. 출력 순서는 \[LLM 공감·요약 1\~2문장\] → \[고정 템플릿\].

mock\_data.py 에 아래 템플릿 4개를 dict로 추가 (기존 데이터 스타일에 맞춰):

GUIDE\_TEMPLATES \= {

    "입금송금": """\*\*지금 제일 먼저 할 일 — 지급정지 신청\*\*

1\. 🚨 \*\*즉시 송금한 은행 고객센터에 전화해서 "보이스피싱 지급정지"를 요청하세요.\*\*

   (은행 앱 내 신고 메뉴 또는 대표번호. 시간이 생명입니다)

2\. 경찰청 112 또는 전기통신금융사기 통합신고센터 ☎ 112 신고

3\. 금융감독원 ☎ 1332 피해구제 상담

4\. 추가 입금 요구는 무조건 거절하세요. "복구해주겠다"는 연락도 2차 사기입니다.""",

    "링크클릭앱설치": """\*\*기기와 계정을 지키는 순서\*\*

1\. 휴대폰을 비행기 모드로 전환 (원격제어 차단)

2\. 설치한 앱 즉시 삭제, 가능하면 백신 검사 (시티즌코난 앱 활용 가능)

3\. 은행 앱 비밀번호·공동인증서 재발급, 주요 계정 비밀번호 변경

4\. 통신사 고객센터에서 소액결제 차단 신청

5\. 명의도용 확인: 엠세이퍼(msafer.or.kr)에서 내 명의 개통 이력 조회""",

    "개인정보제공": """\*\*개인정보가 넘어갔을 때 막아야 할 2차 피해\*\*

1\. 엠세이퍼(msafer.or.kr)에서 명의도용 개통 확인 \+ 가입제한 신청

2\. 금융감독원 개인정보노출자 사고예방시스템(pd.fss.or.kr) 등록

   → 내 명의 계좌 개설·카드 발급이 제한되어 대포통장 악용을 막습니다

3\. 신분증을 보냈다면 재발급 (분실신고 처리)

4\. 해당 계좌 비밀번호 변경, 은행에 상황 알리기""",

    "접촉초기": """\*\*아직 늦지 않았어요 — 지금 끊어내면 됩니다\*\*

1\. 상대방과의 연락을 중단하세요. 차단을 권합니다

2\. 어떤 경우에도 송금·개인정보 제공·앱 설치를 하지 마세요

3\. 공식기관은 전화로 이체나 앱 설치를 요구하지 않습니다

   → 의심되면 그 기관의 공식 대표번호로 직접 확인 (걸려온 번호 말고\!)

4\. 대화 내용을 캡처해 두세요. 나중에 신고 증거가 됩니다""",

}

개인화 문구 생성:

GUIDE\_INTRO\_SYSTEM \= """사용자의 상황에 공감하는 문장 1\~2개를 한국어로 써라.

\- 사용자를 탓하지 말 것. "당황스러우셨겠어요" 같은 톤

\- 사기 확정 단정 금지. "위험 신호가 보여요" 수준까지만

\- 이어서 구체적 행동 안내가 나올 것이므로, 행동 지시는 쓰지 말 것

\- 2문장 이내, 순수 텍스트만"""

def make\_guide(stage: str, chat\_messages: list\[dict\]) \-\> str:

    intro \= call\_llm(GUIDE\_INTRO\_SYSTEM, chat\_messages, temperature=0.7)

    return intro.strip() \+ "\\n\\n" \+ data.GUIDE\_TEMPLATES\[stage\]

⚠️ 템플릿 안의 기관명·번호(112, 1332, 엠세이퍼, pd.fss.or.kr)는 기획 자료 기준이다. 구현자는 커밋 전에 각 기관 공식 사이트에서 번호·URL이 현재도 유효한지 확인할 것.

---

## 3\. 대응 도구 3종 — 버튼 클릭 시에만 생성

phase \== "guided" 일 때 버튼 3개를 st.columns(3)으로 노출. 클릭하면 대화 전체 \+ 판정된 stage를 넣어 LLM 생성, 결과는 채팅 말풍선으로 출력.

TOOL\_SYSTEMS \= {

    "call\_script": """사용자가 은행/경찰에 신고 전화할 때 그대로 읽을 수 있는 대본을 써라.

형식: ① 첫마디 (본인 소개 \+ 용건 한 문장) ② 피해 내용 설명 (대화에서 파악된

사실만: 언제, 어떤 경로로, 무엇을 요구받았고, 무엇을 제공/송금했는지)

③ 요청 사항 (지급정지/피해구제 등 단계에 맞게) ④ 상담원이 물어볼 만한 질문과 답

대화에 없는 사실(금액, 날짜, 계좌번호)은 지어내지 말고 \[직접 입력\] 으로 표시하라.""",

    "report": """피해 상황 요약 리포트를 써라. 신고·상담 시 제출용.

형식: 사건 개요(3줄 이내) / 시간 순 경과 / 상대방 정보(알려진 것만) /

제공·송금한 것 / 감지된 위험 신호 목록

대화에 없는 정보는 \[확인 필요\]로 표시. 추측 금지.""",

    "checklist": """증거 보존 체크리스트를 써라. 체크박스(- \[ \]) 형식.

항목: 대화 캡처(날짜 보이게), 상대 프로필/계정 캡처, 송금 내역 캡처,

통화 녹음 백업, 상대 계좌·전화번호 기록, 원본 삭제 금지 안내

사용자 상황(피해 단계)에 맞는 항목 위주로 6\~10개.""",

}

def make\_tool(tool: str, stage: str, chat\_messages: list\[dict\]) \-\> str:

    context \= chat\_messages \+ \[{"role": "user",

        "content": f"(시스템 참고: 판정된 피해 단계는 '{stage}')"}\]

    return call\_llm(TOOL\_SYSTEMS\[tool\], context, temperature=0.4)

---

## 4\. chat.py 턴 처리 의사코드

if user\_input := st.chat\_input(...):

    append(user\_input)

    phase \= st.session\_state.chat\_phase

    if phase \== "suspicion":

        r \= classify\_suspicion(history)

        if r\["label"\] \== "근거부족" and st.session\_state.ask\_count\["suspicion"\] \< 2:

            st.session\_state.ask\_count\["suspicion"\] \+= 1

            reply(r\["follow\_up"\])

        elif r\["label"\] \== "낮음":

            reply("현재 내용만으로는 사기 가능성이 낮아 보여요. 다만 앞으로 "

                  "개인정보·입금·링크 클릭을 요구받으면 꼭 다시 확인해 주세요\!")

        else:  \# 의심 (근거부족 2회 초과 시에도 의심으로 진행: 안전 우선)

            st.session\_state.signals \+= r.get("signals", \[\])

            st.session\_state.chat\_phase \= "damage\_stage"

            s \= classify\_damage\_stage(history)          \# 같은 턴에 이어서

            if s\["stage"\] \== "근거부족":

                st.session\_state.ask\_count\["damage\_stage"\] \+= 1

                reply("몇 가지 위험 신호가 보여요. 정확한 대응을 안내해 드리기 위해 "

                      "하나만 확인할게요.\\n\\n" \+ s\["follow\_up"\])

            else:

                finish\_with\_guide(s\["stage"\])

    elif phase \== "damage\_stage":

        s \= classify\_damage\_stage(history)

        if s\["stage"\] \== "근거부족" and st.session\_state.ask\_count\["damage\_stage"\] \< 2:

            st.session\_state.ask\_count\["damage\_stage"\] \+= 1

            reply(s\["follow\_up"\])

        else:

            stage \= s\["stage"\] if s\["stage"\] \!= "근거부족" else "접촉초기"  \# 보수적 기본값

            finish\_with\_guide(stage)

    elif phase \== "guided":

        \# 추가 질문이 오면 가이드 문맥 유지한 일반 응대 (선택 구현)

        \# 새 상담은 리셋 버튼 유도

        ...

def finish\_with\_guide(stage):

    st.session\_state.damage\_stage \= stage

    st.session\_state.chat\_phase \= "guided"

    reply(make\_guide(stage, history))

    \# 이후 렌더 루프에서 버튼 3개 노출

에러 처리: call\_llm에서 requests 예외 발생 시 "지금 분석 서버 연결이 원활하지 않아요. 잠시 후 다시 시도해 주세요." 출력하고 phase 유지. API 오류로 앱이 죽으면 안 된다 (try/except 필수).

---

## 5\. 보안 — 반드시 지킬 것

1. 프로젝트 루트 `.gitignore`에 다음 줄 추가 (없으면 파일 생성):  
     
   .streamlit/secrets.toml  
     
   \_\_pycache\_\_/  
     
   venv/  
     
2. `.streamlit/secrets.toml` 로컬 생성:  
     
   UPSTAGE\_API\_KEY \= "여기에\_팀\_API\_키"  
     
3. **이 파일은 절대 커밋 금지.** 커밋 전 `git status`로 secrets.toml이 안 뜨는지 확인.  
4. 배포(Streamlit Cloud)에는 앱 관리 화면 → Settings → Secrets 에 같은 내용을 입력.  
5. requirements.txt 에 `pillow`, `requests` 추가 (현재 streamlit만 있음).

---

## 6\. 구현 순서 (권장)

1. `.gitignore` \+ secrets.toml 세팅 → 커밋에 키 안 들어가는 것부터 확보  
2. services.py: call\_llm \+ parse\_json\_safe → 터미널에서 단독 호출 테스트  
3. classify\_suspicion / classify\_damage\_stage 구현 → 예시 문장 몇 개로 판정 테스트 (예: "상품평 알바인데 3만원 먼저 준대" → 의심 / "친구가 밥값 보내달래" → 낮음·근거부족)  
4. mock\_data.py 에 GUIDE\_TEMPLATES 추가  
5. chat.py 상태 머신 연결  
6. 도구 버튼 3개 \+ make\_tool  
7. streamlit run app.py 로 전체 시나리오 3개(예방/대응/애매) 수동 테스트  
8. 커밋 → push (secrets 미포함 재확인)

