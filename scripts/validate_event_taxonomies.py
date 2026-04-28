"""validate_event_taxonomies — macro × corporate cross-axis 매칭 false positive 정리.

전략:
  1. 두 taxonomy 동시에 매칭된 canonical theme 식별
  2. heuristic 청소:
     - macro=high · corp=medium → corp 매칭 제거 (corp 키워드가 generic 한글에 noise)
     - macro=medium · corp=high → macro 매칭 제거
     - macro=high · corp=high → 양쪽 보존 (legitimate dual-axis)
  3. medium × medium 잔여: LLM에 일괄 질의 ("어느 쪽이 더 적절? 또는 no_match?")
  4. 결과를 두 taxonomy 파일에 in-place 반영, 메타에 'validated: true' 마킹

사용:
  python3 validate_event_taxonomies.py            # heuristic + LLM dry-run
  python3 validate_event_taxonomies.py --apply    # 실제 변경
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import COMPILED, REFERENCE
from llm_client import chat_json, DEFAULT_MODEL

MACRO_PATH = COMPILED / "macro_event_taxonomy.json"
CORP_PATH = COMPILED / "corporate_event_taxonomy.json"
DICT_PATH = COMPILED / "theme_dictionary.json"
LLM_BATCH = 30


def load(p: Path) -> dict:
    return json.loads(p.read_text())


def save(p: Path, d: dict):
    p.write_text(json.dumps(d, ensure_ascii=False, indent=2))


def llm_disambiguate(items: list[dict], macro_vocab: dict, corp_vocab: dict) -> dict:
    """[{canonical, samples, macro_id, corp_id}] → {canonical: 'macro'|'corporate'|'both'|'none'}"""
    SYS = ("당신은 한국 투자 테마 분류기입니다. canonical 테마가 매크로 이벤트에 해당하는지, "
           "기업 이벤트에 해당하는지, 또는 둘 다 / 둘 다 아닌지 정확히 판정합니다.")
    user = f"""# 작업
각 canonical 테마에 대해 (macro_event_id, corporate_event_id) 두 후보 중 어느 쪽이 적절한지 판정.

응답 형식 (JSON):
{{"results": [{{"i": 0, "verdict": "macro" | "corporate" | "both" | "none"}}, ...]}}

verdict 가이드:
- macro: 매크로/거시/정책/시장 환경 이벤트 (corp 매칭은 false positive)
- corporate: 기업 단위 이벤트 (macro 매칭은 false positive)
- both: 진짜 dual-axis (드물게 발생, 명확히 양쪽 의미가 있을 때)
- none: 둘 다 부적절

# 입력
```json
{json.dumps(items, ensure_ascii=False)}
```"""
    out, r = chat_json(SYS, user, model=DEFAULT_MODEL)
    verdicts: dict[str, str] = {}
    for x in out.get("results", []):
        i = x.get("i")
        v = x.get("verdict", "none")
        if i is not None and i < len(items):
            canon = items[i]["canonical"]
            if v in ("macro", "corporate", "both", "none"):
                verdicts[canon] = v
    return verdicts, r.cost_usd


def main():
    apply = "--apply" in sys.argv

    macro = load(MACRO_PATH)
    corp = load(CORP_PATH)
    d = load(DICT_PATH)

    macro_themes = macro.get("themes", {})
    corp_themes = corp.get("themes", {})
    canonicals = d.get("canonical_themes", {})

    cross = sorted(set(macro_themes) & set(corp_themes))
    print(f"[validate] cross-axis 매칭: {len(cross)}")

    # 1. Heuristic 분류
    drop_corp: set[str] = set()
    drop_macro: set[str] = set()
    keep_both: set[str] = set()
    medium_medium: list[str] = []

    for canon in cross:
        mc = macro_themes[canon].get("confidence")
        cc = corp_themes[canon].get("confidence")
        if mc == "high" and cc == "medium":
            drop_corp.add(canon)
        elif mc == "medium" and cc == "high":
            drop_macro.add(canon)
        elif mc == "high" and cc == "high":
            keep_both.add(canon)
        else:  # medium-medium
            medium_medium.append(canon)

    print(f"[heuristic] drop corporate: {len(drop_corp)} (macro=high·corp=medium)")
    print(f"[heuristic] drop macro: {len(drop_macro)} (macro=medium·corp=high)")
    print(f"[heuristic] keep both:  {len(keep_both)} (high×high)")
    print(f"[heuristic] medium×medium → LLM: {len(medium_medium)}")

    # 2. LLM disambiguation for medium×medium
    llm_results: dict[str, str] = {}
    total_cost = 0.0
    if medium_medium:
        # vocabularies
        try:
            mvoc = json.load(open(REFERENCE / "vocabularies" / "macro_event_vocabulary.snapshot.json"))
            cvoc = json.load(open(REFERENCE / "vocabularies" / "corporate_event_vocabulary.snapshot.json"))
        except Exception:
            mvoc, cvoc = {}, {}

        for batch_start in range(0, len(medium_medium), LLM_BATCH):
            batch = medium_medium[batch_start:batch_start + LLM_BATCH]
            items = []
            for i, canon in enumerate(batch):
                info = canonicals.get(canon, {})
                mid = macro_themes[canon].get("matched_event_ids", [""])[0]
                cid = corp_themes[canon].get("matched_event_ids", [""])[0]
                items.append({
                    "i": i,
                    "canonical": canon,
                    "samples": info.get("aliases", [])[:2],
                    "macro_event_id": mid,
                    "corporate_event_id": cid,
                })
            try:
                verdicts, cost = llm_disambiguate(items, mvoc, cvoc)
                total_cost += cost
                llm_results.update(verdicts)
                print(f"  ...{batch_start + len(batch)}/{len(medium_medium)} done, cost=${total_cost:.4f}")
            except Exception as ex:
                print(f"  ! batch failed: {ex}")

    # 3. LLM 결과 → drop set 합치기
    n_drop_corp_llm = 0
    n_drop_macro_llm = 0
    n_drop_both_llm = 0
    for canon, verdict in llm_results.items():
        if verdict == "macro":
            drop_corp.add(canon)
            n_drop_corp_llm += 1
        elif verdict == "corporate":
            drop_macro.add(canon)
            n_drop_macro_llm += 1
        elif verdict == "none":
            drop_corp.add(canon)
            drop_macro.add(canon)
            n_drop_both_llm += 1
        # 'both' → 그대로 유지

    print(f"[llm] verdict 분포: macro={n_drop_corp_llm}, corporate={n_drop_macro_llm}, "
          f"none={n_drop_both_llm}, both={len(llm_results) - n_drop_corp_llm - n_drop_macro_llm - n_drop_both_llm}")
    print(f"[llm] total cost: ${total_cost:.4f}")

    # 4. Apply
    if not apply:
        print(f"\n[validate] dry-run — drop_corp={len(drop_corp)}, drop_macro={len(drop_macro)}. "
              f"적용하려면 --apply")
        return

    for canon in drop_corp:
        corp_themes.pop(canon, None)
    for canon in drop_macro:
        macro_themes.pop(canon, None)

    # update meta
    macro["themes"] = macro_themes
    corp["themes"] = corp_themes
    macro["validated_at"] = datetime.now().isoformat(timespec="seconds")
    corp["validated_at"] = datetime.now().isoformat(timespec="seconds")
    macro["summary"]["n_with_match"] = len(macro_themes)
    corp["summary"]["n_with_match"] = len(corp_themes)

    save(MACRO_PATH, macro)
    save(CORP_PATH, corp)
    print(f"\n[validate] applied — macro {len(macro_themes)} / corporate {len(corp_themes)}")


if __name__ == "__main__":
    main()
