# -*- coding: utf-8 -*-
"""텅장지키미 — 결정론적 판정 엔진

같은 입력 → 항상 같은 출력.
LLM은 이 결과를 문장으로 풀어내는 역할만 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

D = json.loads((Path(__file__).resolve().parent / "signals.json").read_text(encoding="utf-8"))
SIGNALS = D["signals"]
NEG = D["negative_signals"]
STAGES = D["damage_stages"]
FOLLOWUP = {f["slot"]: f for f in D["followup_questions"]}
SECTIONS = D["response_sections"]

# 어떤 시그널이 어떤 슬롯을 채우는지
SLOT_FILLED_BY = {
    "money_sent": ["transferred"],
    "app_installed": ["app_installed", "B01"],
    "info_given": ["info_given", "F02", "F03"],
    "who_contacted": ["A05", "F01", "H02"],
    "what_requested": ["A02", "B01", "C01", "D01", "D05", "E04", "F02", "F03", "G01", "H01"],
    "channel": ["B03", "B04", "C04", "E02", "G03"],
}


def _hit(text: str, patterns: list[str]) -> bool:
    return any(p in text for p in patterns)


def detect_signals(text: str) -> tuple[list[dict], list[dict]]:
    matched = [s for s in SIGNALS if _hit(text, s["patterns"])]
    calmers = [n for n in NEG if _hit(text, n["patterns"])]
    return matched, calmers


def detect_stage(text: str) -> dict:
    for st in sorted(STAGES, key=lambda x: x["priority"]):
        if st["patterns"] and _hit(text, st["patterns"]):
            return st
    return [s for s in STAGES if s["id"] == "initial"][0]


def decide(matched: list[dict], calmers: list[dict]) -> str:
    strong = sum(1 for s in matched if s["weight"] == 3)
    medium = sum(1 for s in matched if s["weight"] == 2)
    medium = max(0, medium - len(calmers))          # 안심 신호가 중 시그널을 상쇄
    if strong >= 1 or medium >= 2:
        return "suspected"
    if medium == 1:
        return "insufficient"
    return "unlikely"


def missing_slots(text: str, matched: list[dict], stage: dict) -> list[str]:
    mids = {s["id"] for s in matched} | {stage["id"]}
    out = []
    for slot, fillers in SLOT_FILLED_BY.items():
        if not (set(fillers) & mids):
            out.append(slot)
    return out


STAGE_SLOT_ORDER = ["money_sent", "app_installed", "info_given"]  # 심각도 순 (STAGES priority와 일치)


def stage_followup(asked: set[str]) -> dict | None:
    """피해 단계가 'initial'(기본값 폴백)로 나왔을 때 — 정말 접촉초기인지 정보가
    부족한 것뿐인지 구분이 안 되므로, 아직 안 물어본 슬롯 중 하나를 되묻는다.
    다 물어봤으면 None → 호출부에서 접촉초기로 확정."""
    for slot in STAGE_SLOT_ORDER:
        if slot not in asked:
            f = FOLLOWUP[slot]
            return {"slot": slot, "question": f["question"]}
    return None


def diagnose(text: str) -> dict:
    text = text.replace(" ", "") + " " + text          # 띄어쓰기 편차 흡수
    matched, calmers = detect_signals(text)
    stage = detect_stage(text)
    verdict = decide(matched, calmers)

    sect = SECTIONS[verdict]
    sections = sect.get(stage["id"]) or sect.get("*")

    result = {
        "verdict": verdict,
        "matched_signals": [
            {"id": s["id"], "label": s["label"], "weight": s["weight"], "explain": s["explain"]}
            for s in sorted(matched, key=lambda x: -x["weight"])
        ],
        "calming_signals": [{"id": n["id"], "label": n["label"], "explain": n["explain"]} for n in calmers],
        "signal_score": {
            "strong": sum(1 for s in matched if s["weight"] == 3),
            "medium": sum(1 for s in matched if s["weight"] == 2),
            "calmers": len(calmers),
        },
        "damage_stage": stage["id"],
        "damage_stage_label": stage["label"],
        "stage_headline": stage["headline"],
        "category_hints": sorted({s["category_hint"] for s in matched if s["category_hint"]}),
        "scenario_hints": sorted({s["scenario_hint"] for s in matched if s["scenario_hint"]}),
        "sections": sections,
        "refund_eligible": None,
        "followups": [],
    }

    # 지급정지 가능 여부 (통신사기피해환급법 적용 대상 판정)
    cats = set(result["category_hints"])
    if cats & {"investment_scam", "romance_scam", "secondhand_scam"}:
        result["refund_eligible"] = False
    elif cats & {"voice_phishing", "smishing", "messenger_impersonation", "loan_scam"}:
        result["refund_eligible"] = True

    if verdict == "insufficient":
        slots = missing_slots(text, matched, stage)[:2]
        result["followups"] = [
            {"slot": s, "reason": FOLLOWUP[s]["missing_reason"], "question": FOLLOWUP[s]["question"]}
            for s in slots
        ]
    return result


# ─────────────────────────────────────────────
if __name__ == "__main__":
    CASES = [
        ("1-A 기관사칭", "어제 카드 배송 왔다고 전화가 왔는데 저는 신청한 적이 없거든요 그래서 명의도용인 것 같다고 하니까 "
         "소비자원에 접수해준다고 해서 번호 알려준 데로 전화했더니 서울중앙지검이라면서 제 계좌가 대포통장으로 쓰였다고 하네요 "
         "지금 피해자인지 가해자인지 불분명하다고 약식조사 진행한다는데 통화 내용 아무한테도 말하면 안 된다고 하고 스피커폰으로 하래요", "suspected"),
        ("1-B 악성앱", "조사 진행하려면 앱을 설치해야 한다고 해서 링크로 하나 설치했어요", "suspected"),
        ("1-C 송금완료", "방금 3200 보냈어요 안전계좌로 옮겨두면 조사 끝나고 돌려준다고 해서요", "suspected"),
        ("1-D 팀미션", "리뷰 몇 개 쓰니까 진짜로 3만원이 들어왔어요 근데 이번엔 30만원을 먼저 결제하래요 "
         "다른 사람들은 다 했다는데 저만 안 하면 정산이 안 된다고 해서요", "suspected"),
        ("2-A 로맨스+투자", "데이팅앱에서 만난 사람인데 영상통화는 계속 미뤘어요 투자 거래소 알려줘서 넣었고 "
         "지금 출금이 안 되는데 소득세 15% 먼저 내라고 해요", "suspected"),
        ("2-C 2차사기", "피해금 회수 전문이라고 DM이 왔는데 착수금은 50만원이래요", "suspected"),
        ("3-A 정상거래", "당근에서 아이패드 사려고 하는데요 내일 지하철역에서 만나서 실물 보고 현금으로 주기로 했어요 "
         "판매자가 계좌로 미리 보내라는 말은 안 했고요", "unlikely"),
        ("3-B 정보질의", "요즘 20대가 많이 당하는 사기가 뭐예요? 예방하려고 알아보려고요", "unlikely"),
        ("근거부족", "모르는 번호로 전화가 왔는데 좀 이상했어요", "unlikely"),
        ("근거부족2", "택배 문자가 왔는데 좀 이상해요", "insufficient"),
    ]

    ok = 0
    for name, txt, expect in CASES:
        r = diagnose(txt)
        good = r["verdict"] == expect
        ok += good
        sc = r["signal_score"]
        print(f"{'✓' if good else '✗'} {name:14s} → {r['verdict']:12s} (기대 {expect})  "
              f"강{sc['strong']} 중{sc['medium']} 안심{sc['calmers']}  단계={r['damage_stage_label']}  "
              f"지급정지={r['refund_eligible']}")
        if r["matched_signals"]:
            print(f"    시그널: {', '.join(s['label'] for s in r['matched_signals'][:4])}")
        if r["followups"]:
            print(f"    되물음: {r['followups'][0]['question'][:45]}…")

    print(f"\n{ok}/{len(CASES)} 통과")

    print("\n── 재현성 검사 (동일 입력 5회) ──")
    base = json.dumps(diagnose(CASES[0][1]), ensure_ascii=False, sort_keys=True)
    print("동일:", all(json.dumps(diagnose(CASES[0][1]), ensure_ascii=False, sort_keys=True) == base for _ in range(5)))
