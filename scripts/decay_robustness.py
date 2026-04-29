"""decay_robustness — Future-B + Future-C 분석.

1. **Theme decay curve**: 7d / 30d / 60d / 90d alpha 진화 패턴
   → 어떤 신호가 단기 효과 vs 장기 효과 다른지 측정

2. **Robustness / skew test**: outlier 1-2개 제거 시 분포 변화
   → 평균 alpha 가 outlier 가 만든 건지 robust 한 건지 검증

출력:
  - data/reference/compiled/decay_analysis.json
  - data/reference/compiled/robustness_analysis.json
  - VAULT/validation/decay_robustness.md
"""
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import COMPILED, VAULT

OBS_PATH = COMPILED / "forward_returns.json"
DECAY_OUT = COMPILED / "decay_analysis.json"
ROBUST_OUT = COMPILED / "robustness_analysis.json"
MD_OUT = VAULT / "validation" / "decay_robustness.md"

WINDOWS = ["7d", "30d", "60d", "90d"]


def trim_mean(arr: list[float], trim_pct: float = 0.05) -> float:
    """양 끝 trim_pct 씩 제외한 평균. outlier 영향 줄임."""
    if not arr:
        return 0.0
    s = sorted(arr)
    n = len(s)
    cut = int(n * trim_pct)
    if cut == 0:
        return statistics.mean(s)
    return statistics.mean(s[cut:n-cut])


def compute_decay(observations: list[dict]) -> dict:
    """채널·event_type·signal·canonical_theme 별 7d→90d alpha curve."""
    out = {"by_channel": {}, "by_event_type": {}, "by_signal": {}, "by_canonical": {}}

    # Channel level
    by_ch: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_ev: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    by_sig: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for o in observations:
        ch = o.get("channel")
        ev = o.get("event_type", "미해당")
        sigs = o.get("signals") or []
        for w in WINDOWS:
            a = o["returns"].get(f"alpha_{w}")
            if a is None:
                continue
            if ch:
                by_ch[ch][w].append(a)
            by_ev[ev][w].append(a)
            for s in sigs:
                by_sig[s][w].append(a)

    def to_decay(grp_dict, min_n=50):
        result = {}
        for k, wmap in grp_dict.items():
            decay = {}
            for w in WINDOWS:
                arr = wmap.get(w, [])
                if len(arr) < min_n:
                    decay[w] = None
                    continue
                decay[w] = {
                    "n": len(arr),
                    "mean": round(statistics.mean(arr), 5),
                    "trim_mean_5pct": round(trim_mean(arr, 0.05), 5),
                    "median": round(statistics.median(arr), 5),
                }
            # decay shape: 7d → 90d 추세
            valid = [decay[w] for w in WINDOWS if decay[w]]
            if len(valid) >= 2:
                first = valid[0]["mean"]
                last = valid[-1]["mean"]
                shape = "rising" if last > first + 0.005 else \
                        "falling" if last < first - 0.005 else "flat"
                decay["_shape"] = shape
                decay["_amplitude"] = round(last - first, 5)
            result[k] = decay
        return result

    out["by_channel"] = to_decay(by_ch, min_n=100)
    out["by_event_type"] = to_decay(by_ev, min_n=50)
    out["by_signal"] = to_decay(by_sig, min_n=200)
    return out


def compute_robustness(observations: list[dict], window: str = "90d") -> dict:
    """outlier 제거 후 분포 변화. window 기준."""
    out = {}

    # 채널별
    by_ch: dict[str, list[float]] = defaultdict(list)
    by_ev: dict[str, list[float]] = defaultdict(list)
    by_canon: dict[str, list[float]] = defaultdict(list)

    for o in observations:
        ch = o.get("channel")
        ev = o.get("event_type", "미해당")
        a = o["returns"].get(f"alpha_{window}")
        if a is None:
            continue
        if ch:
            by_ch[ch].append(a)
        by_ev[ev].append(a)

    def robust_stats(arr: list[float]) -> dict:
        if len(arr) < 30:
            return None
        n = len(arr)
        s = sorted(arr)
        return {
            "n": n,
            "raw_mean": round(statistics.mean(arr), 5),
            "trim_mean_5pct": round(trim_mean(arr, 0.05), 5),
            "trim_mean_10pct": round(trim_mean(arr, 0.10), 5),
            "median": round(statistics.median(arr), 5),
            "p25": round(s[n // 4], 5),
            "p75": round(s[3 * n // 4], 5),
            "skew_top5_pct": round(statistics.mean(s[-int(n*0.05):]) if int(n*0.05) > 0 else 0, 5),
            "skew_bot5_pct": round(statistics.mean(s[:int(n*0.05)]) if int(n*0.05) > 0 else 0, 5),
        }

    out["window"] = window
    out["by_channel"] = {k: robust_stats(v) for k, v in by_ch.items()}
    out["by_event_type"] = {k: robust_stats(v) for k, v in by_ev.items()}
    return out


def render_md(decay: dict, robust: dict) -> str:
    today = datetime.now().date().isoformat()
    out = [f"""---
type: validation
last_updated: {today}
tags: [validation, decay, robustness, auto]
---

# Forward α — Decay & Robustness 분석

> 7d/30d/60d/90d alpha 진화 (decay) + outlier 영향 (robustness).
> 자동 갱신: `{datetime.now().isoformat(timespec='seconds')}`

## 1. Channel Decay — 7d → 90d alpha 진화

"""]
    out.append("| Channel | 7d α | 30d α | 60d α | 90d α | shape | amplitude |")
    out.append("|---|---:|---:|---:|---:|---|---:|")
    for ch, d in (decay.get("by_channel") or {}).items():
        cells = []
        for w in WINDOWS:
            v = d.get(w)
            cells.append(f"{(v['mean'] if v else 0)*100:+.1f}%" if v else "—")
        shape = d.get("_shape", "?")
        amp = d.get("_amplitude")
        amp_str = f"{amp*100:+.1f}%p" if amp is not None else "—"
        out.append(f"| {ch} | {' | '.join(cells)} | {shape} | {amp_str} |")
    out.append("\n→ **shape**: 양의 alpha가 시간 따라 더 커지면 *rising* (장기 신호), 작아지면 *falling* (단기 noise)")

    out.append("\n## 2. Event Type Decay")
    out.append("\n| Event | 7d α | 30d α | 60d α | 90d α | shape |")
    out.append("|---|---:|---:|---:|---:|---|")
    rows = []
    for ev, d in (decay.get("by_event_type") or {}).items():
        e30 = d.get("30d")
        if not e30: continue
        cells = []
        for w in WINDOWS:
            v = d.get(w)
            cells.append(f"{(v['mean'] if v else 0)*100:+.1f}%" if v else "—")
        rows.append((e30["mean"], ev, cells, d.get("_shape", "?")))
    rows.sort(reverse=True)
    for _, ev, cells, shape in rows:
        out.append(f"| {ev} | {' | '.join(cells)} | {shape} |")

    out.append("\n## 3. Signal Decay")
    out.append("\n| Signal | 7d α | 30d α | 60d α | 90d α | shape |")
    out.append("|---|---:|---:|---:|---:|---|")
    rows = []
    for s, d in (decay.get("by_signal") or {}).items():
        e30 = d.get("30d")
        if not e30: continue
        cells = []
        for w in WINDOWS:
            v = d.get(w)
            cells.append(f"{(v['mean'] if v else 0)*100:+.1f}%" if v else "—")
        rows.append((e30["mean"], s, cells, d.get("_shape", "?")))
    rows.sort(reverse=True)
    for _, s, cells, shape in rows:
        out.append(f"| {s} | {' | '.join(cells)} | {shape} |")

    # Robustness
    out.append(f"\n\n## 4. Robustness — 90d α (raw vs trim mean)")
    out.append("\n| Channel | n | raw mean | trim 5% | trim 10% | median | top 5% | bot 5% |")
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for ch, s in (robust.get("by_channel") or {}).items():
        if not s: continue
        out.append(
            f"| {ch} | {s['n']} | {s['raw_mean']*100:+.1f}% | "
            f"{s['trim_mean_5pct']*100:+.1f}% | {s['trim_mean_10pct']*100:+.1f}% | "
            f"{s['median']*100:+.1f}% | {s['skew_top5_pct']*100:+.1f}% | "
            f"{s['skew_bot5_pct']*100:+.1f}% |"
        )
    out.append("\n→ **raw vs trim 차이가 크면 outlier 영향 크다는 신호**. 진짜 alpha 는 trim mean 또는 median 기준으로.")

    out.append(f"\n\n## 5. Event Type Robustness")
    out.append("\n| Event | n | raw mean | trim 5% | median | top 5% |")
    out.append("|---|---:|---:|---:|---:|---:|")
    rows = []
    for ev, s in (robust.get("by_event_type") or {}).items():
        if not s: continue
        rows.append((s["raw_mean"], ev, s))
    rows.sort(reverse=True)
    for _, ev, s in rows:
        out.append(
            f"| {ev} | {s['n']} | {s['raw_mean']*100:+.1f}% | "
            f"{s['trim_mean_5pct']*100:+.1f}% | {s['median']*100:+.1f}% | "
            f"{s['skew_top5_pct']*100:+.1f}% |"
        )

    return "\n".join(out)


def main():
    if not OBS_PATH.exists():
        print(f"[decay_robust] {OBS_PATH} 없음 — forward_validator 먼저")
        return
    payload = json.loads(OBS_PATH.read_text())
    obs = payload.get("observations") or []
    print(f"[decay_robust] observations: {len(obs)}")

    decay = compute_decay(obs)
    robust = compute_robustness(obs, "90d")

    DECAY_OUT.write_text(json.dumps(decay, ensure_ascii=False, indent=2))
    ROBUST_OUT.write_text(json.dumps(robust, ensure_ascii=False, indent=2))

    MD_OUT.parent.mkdir(parents=True, exist_ok=True)
    MD_OUT.write_text(render_md(decay, robust))

    print(f"[decay_robust] → {DECAY_OUT}")
    print(f"[decay_robust] → {ROBUST_OUT}")
    print(f"[decay_robust] → {MD_OUT}")

    # 콘솔 요약
    print("\n=== Channel decay shape ===")
    for ch, d in (decay.get("by_channel") or {}).items():
        cells = " → ".join(
            f"{(d.get(w, {}) or {}).get('mean', 0)*100:+.1f}%" if d.get(w) else "—"
            for w in WINDOWS
        )
        print(f"  {ch:<15} {cells}  [{d.get('_shape','?')}]")


if __name__ == "__main__":
    main()
