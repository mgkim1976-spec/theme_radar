"""alpha_lookups — 과거 α 패턴을 차원별·윈도우별로 집계해 lookup 테이블 생성.

차원:
  - by_channel_signal: (channel, signal) → α stats (가장 예측력 높음)
  - by_event_type: event_type → α stats
  - by_canonical: canonical theme → α stats (n>=5)
  - by_channel: channel → α stats (백업용)

윈도우: 7d, 30d, 60d, 90d (각각 alpha_<w>d)

출력: data/reference/compiled/alpha_lookups.json

daily_alpha_digest.py 가 이 lookup 으로 신규 mention 의 expected α 계산.
"""
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import COMPILED

FR_PATH = COMPILED / "forward_returns.json"
TD_PATH = COMPILED / "theme_dictionary.json"
OUT_PATH = COMPILED / "alpha_lookups.json"

WINDOWS = ["7d", "30d", "60d", "90d"]
MIN_N_CHANNEL_SIGNAL = 50
MIN_N_EVENT_TYPE = 30
MIN_N_CANONICAL = 5
MIN_N_CHANNEL = 30


def stats(arr: list[float]) -> dict:
    if not arr:
        return None
    n = len(arr)
    arr_s = sorted(arr)
    return {
        "n": n,
        "mean": round(sum(arr) / n, 5),
        "median": round(arr_s[n // 2], 5),
        "win_rate": round(sum(1 for x in arr if x > 0) / n, 4),
    }


def aggregate_multi_window(buckets: dict) -> dict:
    """{key: {window: [α_values]}} → {key: {window: stats}} (None when empty)."""
    out = {}
    for key, by_w in buckets.items():
        per_w = {}
        for w in WINDOWS:
            per_w[w] = stats(by_w.get(w, []))
        out[key] = per_w
    return out


def main():
    if not FR_PATH.exists():
        print(f"[alpha_lookups] {FR_PATH} 없음 — forward_validator 먼저 실행")
        return
    obs = json.loads(FR_PATH.read_text()).get("observations", [])

    td = json.loads(TD_PATH.read_text()).get("canonical_themes", {}) if TD_PATH.exists() else {}
    alias_to_canon: dict[str, str] = {}
    for canon, info in td.items():
        alias_to_canon[canon] = canon
        for a in info.get("aliases", []):
            alias_to_canon[a] = canon

    # nested defaultdict for multi-window
    def new_bucket():
        return defaultdict(lambda: defaultdict(list))

    by_cs = new_bucket()
    by_evt = new_bucket()
    by_canon = new_bucket()
    by_ch = new_bucket()

    for o in obs:
        r = o.get("returns") or {}
        ch = o.get("channel", "")
        evt = o.get("event_type") or "미해당"
        canon = alias_to_canon.get(o.get("theme_name", ""))

        for w in WINDOWS:
            a = r.get(f"alpha_{w}")
            if a is None:
                continue
            by_ch[ch][w].append(a)
            by_evt[evt][w].append(a)
            if canon:
                by_canon[canon][w].append(a)
            for sig in o.get("signals", []):
                by_cs[f"{ch}|{sig}"][w].append(a)

    def filter_by_min(buckets: dict, min_n: int) -> dict:
        agg = aggregate_multi_window(buckets)
        # 90d n 기준으로 cutoff (가장 보수적인 윈도우)
        return {
            k: v for k, v in agg.items()
            if v.get("90d") and v["90d"]["n"] >= min_n
        }

    out = {
        "version": 2,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "windows": WINDOWS,
        "metric": "alpha_<window> (index-relative: KRX→069500, US→SPY)",
        "min_n": {
            "channel_signal": MIN_N_CHANNEL_SIGNAL,
            "event_type": MIN_N_EVENT_TYPE,
            "canonical": MIN_N_CANONICAL,
            "channel": MIN_N_CHANNEL,
        },
        "by_channel": filter_by_min(by_ch, MIN_N_CHANNEL),
        "by_channel_signal": filter_by_min(by_cs, MIN_N_CHANNEL_SIGNAL),
        "by_event_type": filter_by_min(by_evt, MIN_N_EVENT_TYPE),
        "by_canonical": filter_by_min(by_canon, MIN_N_CANONICAL),
    }

    COMPILED.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    print(f"[alpha_lookups] channel×signal {len(out['by_channel_signal'])}, "
          f"event_type {len(out['by_event_type'])}, "
          f"canonical {len(out['by_canonical'])}, "
          f"channel {len(out['by_channel'])}")
    print(f"[alpha_lookups] → {OUT_PATH}")

    # 미리보기 — 30d 와 90d 모두 양수인 channel×signal
    consistent = []
    for k, v in out["by_channel_signal"].items():
        s30 = v.get("30d")
        s90 = v.get("90d")
        if s30 and s90 and s30["median"] > 0 and s90["median"] > 0:
            consistent.append((k, s30["median"], s90["median"], s90["n"]))
    consistent.sort(key=lambda r: -(r[1] + r[2]))
    print(f"\n  consistent (30d & 90d median > 0) — {len(consistent)} combos:")
    for k, m30, m90, n in consistent[:8]:
        print(f"    {k:<40} 30d={m30*100:>5.2f}% / 90d={m90*100:>5.2f}% (n={n})")


if __name__ == "__main__":
    main()
