"""phase_tracker — canonical theme별 현재 phase 추정.

전략 (v1):
  1. theme_dictionary 의 first_seen → 테마 발생 시점
  2. regime_alignment 에서 theme → macro_event 매핑 추출
  3. phase_mapping 에서 macro_event → historical event 매핑 추출
  4. historical event 의 phase_dates 사용해 phase 길이 계산
  5. 첫 등장 후 경과일 → 현재 phase 추정 (1/2/3/4+)
  6. 출력: data/reference/compiled/phase_tracking.json

한계:
  - 테마 first_seen 이 historical event 시작과 정확히 일치하지 않을 수 있음
  - 반복 가능한 macro event (Fed pivot 등) 는 phase 가 일회성 아님
  → 매핑 score 기반 confidence 표시
"""
import json
import sys
from datetime import datetime, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import REFERENCE, COMPILED

THEME_DICT_PATH = COMPILED / "theme_dictionary.json"
REGIME_ALIGN_PATH = COMPILED / "regime_alignment.json"
PHASE_MAP_PATH = COMPILED / "phase_mapping.json"
PHASE_KB_PATH = REFERENCE / "vocabularies" / "phase_kb.snapshot.json"
OUT_PATH = COMPILED / "phase_tracking.json"


def parse_first_seen(s: str) -> date | None:
    if not s or len(s) < 8:
        return None
    try:
        return datetime.strptime(s[:8], "%Y%m%d").date()
    except ValueError:
        return None


def compute_phase_boundaries(phase_dates: list[str]) -> list[int]:
    """phase_dates → cumulative day offsets from phase 1 start. e.g. [0, 44, 168, 211]."""
    if not phase_dates:
        return []
    try:
        ds = [datetime.strptime(d, "%Y-%m-%d").date() for d in phase_dates]
    except ValueError:
        return []
    base = ds[0]
    return [(d - base).days for d in ds]


def estimate_phase(elapsed_days: int, boundaries: list[int]) -> tuple[int, str]:
    """elapsed days → phase number (1..N+1)."""
    if not boundaries or elapsed_days < 0:
        return 0, "no_boundary"
    # boundaries[i] = cumulative days at start of phase i+1 (i=0 → phase 1 start = 0)
    # phase k 적용 범위: boundaries[k-1] <= elapsed < boundaries[k]
    if elapsed_days < boundaries[0]:
        return 1, "pre_event"  # 이론상 0
    for i in range(len(boundaries) - 1):
        if boundaries[i] <= elapsed_days < boundaries[i + 1]:
            return i + 1, "in_phase"
    # past final boundary
    return len(boundaries), "post_final"


def confidence_label(map_score: float) -> str:
    if map_score >= 50:
        return "HIGH"
    if map_score >= 30:
        return "MEDIUM"
    return "LOW"


def main():
    for p in [THEME_DICT_PATH, REGIME_ALIGN_PATH, PHASE_MAP_PATH, PHASE_KB_PATH]:
        if not p.exists():
            print(f"[phase_tracker] 누락: {p}")
            return

    theme_dict = json.loads(THEME_DICT_PATH.read_text()).get("canonical_themes", {})
    regime_align = json.loads(REGIME_ALIGN_PATH.read_text()).get("themes", {})
    phase_map = json.loads(PHASE_MAP_PATH.read_text()).get("mapping", {})
    phase_kb_events = {e["event_id"]: e for e in json.loads(PHASE_KB_PATH.read_text()).get("events", [])}

    today = date.today()
    out: dict[str, dict] = {}
    n_estimated = 0
    n_skipped = 0
    phase_dist: dict[int, int] = {}

    for theme_name, align in regime_align.items():
        macro_event_id = align.get("event_id")
        if not macro_event_id:
            n_skipped += 1
            continue

        # canonical theme lookup (slug match)
        td = theme_dict.get(theme_name) or theme_dict.get(theme_name.lower())
        if not td:
            # try by tag_members
            td = next(
                (v for v in theme_dict.values() if theme_name in v.get("tag_members", [])),
                None,
            )
        if not td:
            n_skipped += 1
            continue

        first_seen = parse_first_seen(td.get("first_seen", ""))
        if not first_seen:
            n_skipped += 1
            continue

        # macro → historical (top 1)
        hist_matches = phase_map.get(macro_event_id, [])
        if not hist_matches:
            n_skipped += 1
            continue
        top = hist_matches[0]
        hist_event_id = top.get("historical_event_id")
        map_score = top.get("score", 0)
        hist_event = phase_kb_events.get(hist_event_id)
        if not hist_event:
            n_skipped += 1
            continue

        phase_dates = hist_event.get("phase_dates", [])
        boundaries = compute_phase_boundaries(phase_dates)
        if len(boundaries) < 2:
            n_skipped += 1
            continue

        elapsed = (today - first_seen).days
        phase_num, phase_kind = estimate_phase(elapsed, boundaries)
        phases_def = hist_event.get("phases", {})
        phase_desc = (phases_def.get(str(phase_num), {}) or {}).get("description", "")

        # 마지막 phase 를 넘어선 경우 = 4+ (장기 지속 상태)
        if phase_kind == "post_final":
            phase_label = f"{phase_num}+"
            reason = f"elapsed {elapsed}d > final boundary {boundaries[-1]}d → 지속 상태"
        else:
            phase_label = str(phase_num)
            reason = f"elapsed {elapsed}d in phase {phase_num} (boundaries={boundaries})"

        out[theme_name] = {
            "first_seen": td.get("first_seen", ""),
            "elapsed_days": elapsed,
            "macro_event_id": macro_event_id,
            "historical_event_id": hist_event_id,
            "historical_event_name": top.get("name", ""),
            "phase_boundaries_days": boundaries,
            "current_phase": phase_label,
            "phase_description": phase_desc,
            "confidence": confidence_label(map_score),
            "map_score": round(map_score, 1),
            "reason": reason,
        }
        n_estimated += 1
        # phase distribution (use numeric)
        phase_dist[phase_num] = phase_dist.get(phase_num, 0) + 1

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_themes_estimated": n_estimated,
        "n_themes_skipped": n_skipped,
        "phase_distribution": dict(sorted(phase_dist.items())),
        "method": "first_seen + historical phase_dates → elapsed-day phase estimation",
        "themes": out,
    }
    COMPILED.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    print(f"[phase_tracker] estimated {n_estimated}, skipped {n_skipped}")
    print(f"  phase distribution: {payload['phase_distribution']}")
    print(f"  → {OUT_PATH}")


if __name__ == "__main__":
    main()
