"""phase_mapper — macro_event → historical event KB 매핑 + 현재 phase 추정.

전략 (v1, 가벼운 버전):
  1. phase_kb.snapshot.json 의 30개 historical event 의 tags·category 추출
  2. macro_event_vocabulary 의 keywords_ko + causal_chain 과 비교 (RapidFuzz partial)
  3. 각 macro_event_id → 가장 유사한 historical event_id 1-2개 매핑
  4. 출력: data/reference/compiled/phase_mapping.json

phase 추정은 v1에서 보류 (canonical theme의 mention 시작점 기준 추정 가능하지만
시장 실제 phase는 외부 시점 종속이라 별도 모델 필요).
대신 theme 페이지에 "이 macro_event와 유사한 historical 사례" 참고 링크 제공.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz

sys.path.insert(0, str(Path(__file__).parent))
from config import REFERENCE, COMPILED

MACRO_VOCAB_PATH = REFERENCE / "vocabularies" / "macro_event_vocabulary.snapshot.json"
PHASE_KB_PATH = REFERENCE / "vocabularies" / "phase_kb.snapshot.json"
OUT_PATH = COMPILED / "phase_mapping.json"

# macro_event subject_category → historical category 매핑 (curation)
SUBJECT_TO_HISTORICAL_CATS = {
    "central_bank_action": ["통화정책"],
    "geopolitical": ["전쟁/지정학", "핵/WMD", "테러/충격"],
    "fiscal_policy": ["정치/재정"],
    "credit_market": ["금융위기"],
    "energy_market": ["에너지", "에너지/지정학"],
    "regime_change": ["통화정책", "정치/재정"],
}


def macro_to_historical_match(macro_event: dict, historical_events: list[dict]) -> list[dict]:
    """카테고리 기반 매칭. 같은 historical category에 속하는 events 중 fuzzy 추가."""
    subject = macro_event.get("subject_category", "") or ""
    target_cats = SUBJECT_TO_HISTORICAL_CATS.get(subject, [])

    scored = []
    macro_kw = " ".join(macro_event.get("keywords_ko", []) or [])
    for h in historical_events:
        h_cat = h.get("category", "")
        # 카테고리 매칭이 1차 필터
        if target_cats and h_cat not in target_cats:
            continue
        # 이름/태그 fuzzy 추가 점수
        h_text = " ".join([
            h.get("name", "") or "",
            " ".join(h.get("tags", []) or []),
            h.get("description", "") or "",
        ])
        kw_score = fuzz.partial_ratio(macro_kw, h_text) if macro_kw else 0
        scored.append({
            "historical_event_id": h.get("event_id"),
            "name": h.get("name"),
            "category": h.get("category"),
            "date": h.get("date"),
            "score": kw_score,
            "tags": h.get("tags", [])[:5],
        })
    scored.sort(key=lambda x: -x["score"])
    return scored[:3]


def main():
    if not MACRO_VOCAB_PATH.exists() or not PHASE_KB_PATH.exists():
        print(f"[phase_mapper] vocabulary 누락 — sync_vocabularies 먼저 실행")
        return

    vocab = json.loads(MACRO_VOCAB_PATH.read_text())
    phase_kb = json.loads(PHASE_KB_PATH.read_text())

    macro_events = vocab.get("events", {})
    historical = phase_kb.get("events", [])

    print(f"[phase_mapper] macro {len(macro_events)} × historical {len(historical)}")

    mapping: dict[str, list[dict]] = {}
    n_matched = 0
    for eid, e in macro_events.items():
        matches = macro_to_historical_match(e, historical)
        if matches:
            mapping[eid] = matches
            n_matched += 1

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_macro_events": len(macro_events),
        "n_historical_events": len(historical),
        "n_macro_with_match": n_matched,
        "match_strategy": "subject_category + keywords_ko fuzzy",
        "mapping": mapping,
    }
    COMPILED.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"[phase_mapper] {n_matched}/{len(macro_events)} macro events에 historical 매칭")
    print(f"  샘플:")
    for eid, matches in list(mapping.items())[:5]:
        m = matches[0]
        print(f"    {eid:30} → {m['historical_event_id']:30} (score={m['score']})")
    print(f"\n[phase_mapper] → {OUT_PATH}")


if __name__ == "__main__":
    main()
