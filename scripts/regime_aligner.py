"""regime_aligner — 각 canonical theme의 매크로 이벤트와 현재 regime의 적합도 산출.

흐름:
  1. data/reference/vocabularies/regime_state.snapshot.json — 현재 regime
  2. data/reference/compiled/macro_event_taxonomy.json — theme→macro_event 매핑
  3. macro_event vocabulary 의 regime_context 필드 추출
  4. 현재 regime이 regime_context에 포함되면 'aligned', 일부면 'partial', 무관/반대면 'misaligned'

출력: data/reference/compiled/regime_alignment.json
  {
    "current_regime": "OVERHEATING",
    "themes": {
      "<canonical>": {
        "alignment": "aligned" | "partial" | "misaligned" | "neutral",
        "current_regime": "OVERHEATING",
        "event_id": "fed_pivot",
        "event_regime_context": "CONTRACTION 또는 EXPANSION 으로 전환 시 발생 빈도 높음",
        "reason": "..."
      }
    }
  }
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import REFERENCE, COMPILED

REGIME_PATH = REFERENCE / "vocabularies" / "regime_state.snapshot.json"
MACRO_VOCAB_PATH = REFERENCE / "vocabularies" / "macro_event_vocabulary.snapshot.json"
MACRO_TAXONOMY_PATH = COMPILED / "macro_event_taxonomy.json"
OUT_PATH = COMPILED / "regime_alignment.json"

# 5-regime 분류 (investment_ontology와 일치)
REGIMES = {"EXPANSION", "OVERHEATING", "CONTRACTION", "STAGFLATION", "TRANSITIONAL"}


def classify_alignment(current_regime: str, regime_context_text: str) -> tuple[str, str]:
    """current regime이 event의 regime_context에 어떻게 위치하는지 분류.
    return: (alignment, reason)"""
    if not regime_context_text:
        return "neutral", "regime_context 정보 없음"
    t = regime_context_text.upper()
    cur = current_regime.upper()
    # 직접 명시
    if cur in t:
        return "aligned", f"current regime '{cur}'이 event 환경에 명시됨"
    # 'X 또는 Y' 패턴 — 둘 중 하나면 partial
    matches = re.findall(r"(EXPANSION|OVERHEATING|CONTRACTION|STAGFLATION|TRANSITIONAL)", t)
    if matches:
        if cur in matches:
            return "aligned", f"current '{cur}' 일치"
        return "misaligned", f"event 환경은 {matches} (current {cur})"
    # 키워드 기반 fallback
    if cur == "OVERHEATING" and any(k in t for k in ["과열", "긴축", "인플레", "리스크 오프"]):
        return "aligned", f"키워드 매칭 (OVERHEATING)"
    if cur == "EXPANSION" and any(k in t for k in ["성장", "회복", "리스크 온"]):
        return "aligned", f"키워드 매칭 (EXPANSION)"
    return "partial", "regime_context 텍스트는 있지만 명확 매칭 안 됨"


def main():
    if not REGIME_PATH.exists():
        print(f"[regime_aligner] {REGIME_PATH} 없음 — sync_vocabularies 먼저 실행")
        return
    if not MACRO_TAXONOMY_PATH.exists():
        print(f"[regime_aligner] {MACRO_TAXONOMY_PATH} 없음 — macro_event_classifier 먼저 실행")
        return

    regime = json.loads(REGIME_PATH.read_text())
    current = (regime.get("latest_value") or "UNKNOWN").upper()
    print(f"[regime_aligner] 현재 regime: {current}")
    print(f"  score: {regime.get('regime_score')}, confidence: {regime.get('confidence')}")

    vocab = json.loads(MACRO_VOCAB_PATH.read_text())
    events = vocab.get("events", {})

    # Local extensions: upstream vocabulary 의 regime_context 가 비어 있는 경우 보완
    ext_path = REFERENCE / "vocabularies" / "regime_context_extensions.json"
    n_filled = 0
    if ext_path.exists():
        try:
            ext = json.loads(ext_path.read_text())
            ext_ctx = ext.get("regime_context") or {}
            for eid, ctx in ext_ctx.items():
                if eid in events and not events[eid].get("regime_context"):
                    events[eid]["regime_context"] = ctx
                    n_filled += 1
            if n_filled:
                print(f"[regime_aligner] local extensions 적용: {n_filled} events 의 regime_context 보완")
        except Exception as ex:
            print(f"[regime_aligner] extensions 로드 실패 (무시): {ex}")

    taxonomy = json.loads(MACRO_TAXONOMY_PATH.read_text())
    themes = taxonomy.get("themes", {})

    out: dict[str, dict] = {}
    counter = {"aligned": 0, "partial": 0, "misaligned": 0, "neutral": 0}
    for canon, info in themes.items():
        ids = info.get("matched_event_ids") or []
        if not ids:
            continue
        eid = ids[0]
        e = events.get(eid, {})
        ctx = e.get("regime_context", "")
        alignment, reason = classify_alignment(current, ctx)
        counter[alignment] += 1
        out[canon] = {
            "alignment": alignment,
            "current_regime": current,
            "event_id": eid,
            "event_regime_context": ctx,
            "event_severity": e.get("severity"),
            "event_direction": e.get("direction"),
            "reason": reason,
        }

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "current_regime": current,
        "regime_score": regime.get("regime_score"),
        "regime_confidence": regime.get("confidence"),
        "regime_drivers": regime.get("drivers"),
        "summary": counter,
        "themes": out,
    }
    COMPILED.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"\n[regime_aligner] {len(out)} themes (macro 매칭) 적합도 분석:")
    for k, n in counter.items():
        print(f"  {k:12} {n}")
    print(f"\n[regime_aligner] → {OUT_PATH}")


if __name__ == "__main__":
    main()
