"""macro_event_classifier — canonical theme → 이벤트 vocabulary 매핑 (generic).

v2.2부터 macro/corporate 두 vocabulary 모두 처리 가능 (CLI args로 선택).

데이터 소스 (snapshot, investment_ontology에서 vendoring):
  - macro_event_vocabulary.snapshot.json   (42 매크로 이벤트, default)
  - corporate_event_vocabulary.snapshot.json (79 기업 이벤트)

Stage A — Keyword 매칭 (RapidFuzz, LLM 미사용, 비용 0):
  각 canonical theme의 (canonical_tag + aliases 일부)을 모든 이벤트의
  keywords_ko 리스트와 token_set_ratio + partial_ratio로 매칭.
  정규화 + threshold ≥ 85 = high, 75-84 = medium.

Stage B (LLM): 매칭 실패한 canonical 중 mention ≥ 3 만 LLM fallback.

사용:
  python3 macro_event_classifier.py                    # macro (default)
  python3 macro_event_classifier.py --vocab=corporate  # corporate
  python3 macro_event_classifier.py --vocab=corporate --stage-b
  python3 macro_event_classifier.py --vocab=macro --rebuild-cache

출력: data/reference/compiled/{macro|corporate}_event_taxonomy.json
{
  "<canonical_theme>": {
    "matched_event_ids": ["fed_pivot", ...],
    "best_score": 92,
    "matching_keyword": "연준 피벗",
    "method": "keyword_fuzzy",
    "confidence": "high|medium|low",
    "inherited": {
      "severity": "CRITICAL",
      "direction": "mixed",
      "impact_pct": {...},
      "regime_context": "..."
    }
  }
}
"""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz, process

sys.path.insert(0, str(Path(__file__).parent))
from config import REFERENCE, COMPILED, CACHE

VOCAB_DIR = REFERENCE / "vocabularies"
DICT_PATH = COMPILED / "theme_dictionary.json"

# vocab 선택 → 출력 경로 매핑
VOCAB_REGISTRY = {
    "macro": {
        "snapshot": "macro_event_vocabulary.snapshot.json",
        "out": "macro_event_taxonomy.json",
        "cache": "macro_event_llm_cache.json",
    },
    "corporate": {
        "snapshot": "corporate_event_vocabulary.snapshot.json",
        "out": "corporate_event_taxonomy.json",
        "cache": "corporate_event_llm_cache.json",
    },
}

THRESHOLD_HIGH = 85
THRESHOLD_MEDIUM = 75
STAGE_B_BATCH = 30
STAGE_B_MIN_MENTIONS = 3  # cost gate


def _normalize(s: str) -> str:
    """공백/언더스코어 정규화, 영문 소문자, 양끝 공백 제거."""
    if not s:
        return ""
    return s.replace("_", " ").lower().strip()


def load_vocabulary(vocab_key: str) -> dict:
    info = VOCAB_REGISTRY.get(vocab_key)
    if not info:
        raise ValueError(f"unknown vocab: {vocab_key}. valid: {list(VOCAB_REGISTRY.keys())}")
    p = VOCAB_DIR / info["snapshot"]
    if not p.exists():
        raise FileNotFoundError(
            f"{p} 없음 — `python3 scripts/sync_vocabularies.py --apply` 먼저 실행"
        )
    return json.loads(p.read_text())


def vocab_paths(vocab_key: str) -> tuple:
    info = VOCAB_REGISTRY[vocab_key]
    return (
        VOCAB_DIR / info["snapshot"],
        COMPILED / info["out"],
        CACHE / info["cache"],
    )


def build_keyword_index(vocab: dict) -> list[tuple[str, str, str]]:
    """[(keyword_norm, keyword_orig, event_id)] flat 리스트.
    keyword_norm = 정규화 형태 (매칭용), keyword_orig = 표시용."""
    index = []
    for event_id, e in vocab.get("events", {}).items():
        for kw in e.get("keywords_ko", []):
            index.append((_normalize(kw), kw, event_id))
        if e.get("korean_name"):
            index.append((_normalize(e["korean_name"]), e["korean_name"], event_id))
    return index


def _score(cand_norm: str, kw_norm: str) -> int:
    """token_set_ratio + partial_ratio 중 max. 짧은 한글 태그도 매칭."""
    a = fuzz.token_set_ratio(cand_norm, kw_norm)
    b = fuzz.partial_ratio(cand_norm, kw_norm)
    return int(max(a, b))


def classify_one(canonical: str, aliases: list[str],
                 keyword_index: list[tuple[str, str, str]]) -> dict:
    """canonical + aliases → best matching event(s).
    정규화 + token_set/partial max 사용 — 짧은 한글 태그도 substring 매칭됨.
    """
    candidates_raw = [canonical] + (aliases[:8] if aliases else [])
    candidates = [(c, _normalize(c)) for c in candidates_raw if c]

    best_per_event: dict[str, tuple[int, str, str]] = {}
    for cand_orig, cand_norm in candidates:
        if not cand_norm:
            continue
        # 너무 짧으면 partial_ratio가 false positive — 길이 < 3 글자는 token_set만
        for kw_norm, kw_orig, eid in keyword_index:
            if len(cand_norm) < 3 and len(kw_norm) < 3:
                continue
            score = _score(cand_norm, kw_norm)
            if score < THRESHOLD_MEDIUM:
                continue
            prev = best_per_event.get(eid, (0, "", ""))
            if score > prev[0]:
                best_per_event[eid] = (score, kw_orig, cand_orig)

    if not best_per_event:
        return {"matched_event_ids": [], "method": "keyword_fuzzy", "confidence": "none"}

    sorted_events = sorted(best_per_event.items(), key=lambda x: -x[1][0])
    matched_ids = [eid for eid, (s, _, _) in sorted_events if s >= THRESHOLD_MEDIUM]
    best_score, best_kw, best_cand = sorted_events[0][1]
    confidence = "high" if best_score >= THRESHOLD_HIGH else "medium"

    return {
        "matched_event_ids": matched_ids,
        "best_score": best_score,
        "matching_keyword": best_kw,
        "matching_alias": best_cand[:80],
        "method": "keyword_fuzzy",
        "confidence": confidence,
    }


def inherit_metadata(matched_ids: list[str], vocab: dict) -> dict:
    """매칭된 이벤트 중 첫 번째(top score)의 메타데이터 상속."""
    if not matched_ids:
        return {}
    e = vocab.get("events", {}).get(matched_ids[0], {})
    return {
        "severity": e.get("severity"),
        "direction": e.get("direction"),
        "impact_pct": e.get("impact_pct"),
        "regime_context": e.get("regime_context"),
        "subject_category": e.get("subject_category"),
    }


def stage_b_llm(unmatched: list[tuple[str, list[str]]], vocab: dict,
                cache: dict, cache_path: Path = None) -> dict:
    """미매칭 canonical을 LLM에 배치 전달 → event_id 또는 no_match.

    cache 활용 (영구). 새로 호출되는 canonical만 LLM 비용 발생.
    """
    from llm_client import chat_json, DEFAULT_MODEL

    todo = [(c, a) for c, a in unmatched if c not in cache]
    if not todo:
        print(f"[stage_b] cache hit 100% — {len(unmatched)} canonicals 모두 캐시됨")
        return cache

    # vocabulary 요약 (한 번만 prompt에 넣음)
    events = vocab.get("events", {})
    vocab_summary = "\n".join(
        f"- {eid}: {e.get('korean_name','')} — {e.get('description','')[:80]}"
        for eid, e in events.items()
    )
    valid_ids = set(events.keys())
    valid_ids.add("no_match")

    SYS = "당신은 한국 투자 테마를 매크로 이벤트 vocabulary에 정확히 매핑하는 분류기입니다."

    print(f"[stage_b] LLM 호출 — {len(todo)}/{len(unmatched)} todo, "
          f"배치 크기 {STAGE_B_BATCH}, 캐시 {len(cache)}")
    total_cost = 0.0
    n_calls = 0

    for batch_start in range(0, len(todo), STAGE_B_BATCH):
        batch = todo[batch_start:batch_start + STAGE_B_BATCH]
        items = [
            {"i": i, "canonical": c, "samples": a[:2]}  # 2 alias 충분
            for i, (c, a) in enumerate(batch)
        ]
        user = f"""# 매크로 이벤트 Vocabulary
{vocab_summary}

# 분류 대상 ({len(batch)} canonical themes)
```json
{json.dumps(items, ensure_ascii=False)}
```

# 작업
각 canonical theme이 vocabulary 중 어떤 매크로 이벤트와 가장 가까운지 선택.
- 명확히 매칭되는 매크로 이벤트가 있으면 그 event_id (예: "fed_pivot")
- 매크로 이벤트가 아닌 산업·기업·종목 테마면 "no_match"
- 애매하면 "no_match" (false positive 회피)

응답 형식 (JSON만):
{{"results": [{{"i": 0, "event_id": "..."}}, {{"i": 1, "event_id": "no_match"}}, ...]}}"""

        data, r = chat_json(SYS, user, model=DEFAULT_MODEL)
        total_cost += r.cost_usd
        n_calls += 1

        for item in data.get("results", []):
            i = item.get("i")
            eid = item.get("event_id", "no_match")
            if i is None or i >= len(batch):
                continue
            if eid not in valid_ids:
                eid = "no_match"
            canon = batch[i][0]
            cache[canon] = eid

        # resilience: 주기적 저장
        if n_calls % 3 == 0 and cache_path:
            cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
            print(f"  ...{batch_start + len(batch)}/{len(todo)} done, cost=${total_cost:.4f}")

    if cache_path:
        cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    print(f"[stage_b] 완료 — {n_calls} 호출, total ${total_cost:.4f}")
    return cache


def load_llm_cache(cache_path: Path) -> dict:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            return {}
    return {}


def main():
    use_stage_b = "--stage-b" in sys.argv
    min_mentions = STAGE_B_MIN_MENTIONS
    vocab_key = "macro"
    for a in sys.argv[1:]:
        if a.startswith("--min-mentions="):
            min_mentions = int(a.split("=", 1)[1])
        elif a.startswith("--vocab="):
            vocab_key = a.split("=", 1)[1]

    if not DICT_PATH.exists():
        print(f"[event_classifier] {DICT_PATH} 없음 — theme_normalizer 먼저 실행")
        return

    snap_path, out_path, cache_path = vocab_paths(vocab_key)
    vocab = load_vocabulary(vocab_key)
    n_events = len(vocab.get("events", {}))
    keyword_index = build_keyword_index(vocab)
    print(f"[event_classifier:{vocab_key}] vocabulary: {n_events} events, "
          f"{len(keyword_index)} keywords")

    d = json.loads(DICT_PATH.read_text())
    canonical_themes = d.get("canonical_themes", {})
    print(f"[macro_classifier] canonical themes: {len(canonical_themes)}")

    out: dict[str, dict] = {}
    confidence_counter = Counter()
    event_hit_counter: Counter = Counter()
    stage_a_results: dict[str, dict] = {}

    for canon, info in canonical_themes.items():
        result = classify_one(canon, info.get("aliases", []), keyword_index)
        stage_a_results[canon] = result
        confidence_counter[result["confidence"]] += 1
        for eid in result["matched_event_ids"]:
            event_hit_counter[eid] += 1
        if result["matched_event_ids"]:
            result["inherited"] = inherit_metadata(result["matched_event_ids"], vocab)
            out[canon] = result

    # Stage B: LLM fallback for unmatched high-mention canonicals
    if use_stage_b:
        unmatched = [
            (c, info.get("aliases", []))
            for c, info in canonical_themes.items()
            if not stage_a_results[c]["matched_event_ids"]
            and info.get("total_mentions", 0) >= min_mentions
        ]
        print(f"\n[stage_b] 후보: mention ≥ {min_mentions} 인 미매칭 = {len(unmatched)}")
        cache = load_llm_cache(cache_path)
        cache = stage_b_llm(unmatched, vocab, cache, cache_path=cache_path)

        # 캐시 결과 → out 에 병합
        n_added = 0
        n_no_match = 0
        for canon, eid in cache.items():
            if eid == "no_match":
                n_no_match += 1
                continue
            if canon in out:
                continue  # Stage A 이미 매칭
            if canon not in canonical_themes:
                continue  # cache stale
            confidence_counter[result["confidence"]] -= 0  # noop, 카운터 분리
            out[canon] = {
                "matched_event_ids": [eid],
                "method": "llm_fallback",
                "confidence": "llm",
                "inherited": inherit_metadata([eid], vocab),
            }
            event_hit_counter[eid] += 1
            n_added += 1
        print(f"[stage_b] LLM이 {n_added}건 매핑, {n_no_match}건 'no_match'로 판정")

    # 출력
    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "vocabulary_source": snap_path.name,
        "vocab_key": vocab_key,
        "thresholds": {"high": THRESHOLD_HIGH, "medium": THRESHOLD_MEDIUM},
        "summary": {
            "n_canonical_themes": len(canonical_themes),
            "n_with_match": confidence_counter["high"] + confidence_counter["medium"],
            "by_confidence": dict(confidence_counter),
            "top_event_hits": event_hit_counter.most_common(15),
        },
        "themes": out,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    n_match = confidence_counter["high"] + confidence_counter["medium"]
    coverage = round(n_match / max(len(canonical_themes), 1) * 100, 1)
    print(f"[event_classifier:{vocab_key}] coverage: {n_match}/{len(canonical_themes)} ({coverage}%)")
    print(f"  high   : {confidence_counter['high']}")
    print(f"  medium : {confidence_counter['medium']}")
    print(f"  none   : {confidence_counter['none']}")
    print(f"\n[event_classifier:{vocab_key}] Top 15 매칭된 이벤트:")
    for eid, n in event_hit_counter.most_common(15):
        print(f"  {eid:30} {n}")
    print(f"\n[event_classifier:{vocab_key}] → {out_path}")


if __name__ == "__main__":
    main()
