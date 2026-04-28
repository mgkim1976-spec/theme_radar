"""scorecard — forward_returns.json 집계 → 채널·event_type·테마·signal 별 score.

산출:
  - data/reference/scorecard.json (raw)
  - VAULT/validation/scorecard.md (사람 가독)
  - youtuber 페이지에 통계 섹션 (wiki_ingest 통합 시 활용 가능)

지표:
  - mean_return: 산술 평균
  - median_return: 중앙값
  - win_rate: return > 0 비율
  - n_obs: 관측 수 (의미 있는 신호인지 판단)

윈도우: 7d / 30d / 60d / 90d
"""
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import COMPILED, VAULT

INPUT_PATH = COMPILED / "forward_returns.json"
OUT_JSON = COMPILED / "scorecard.json"
OUT_MD = VAULT / "validation" / "scorecard.md"
WINDOWS = ["7d", "30d", "60d", "90d"]
MIN_OBS_FOR_DISPLAY = 5  # 신뢰성 게이트


def aggregate(observations: list[dict], group_key) -> dict:
    """group_key: callable(obs) → str. 그룹별 집계."""
    by_group: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for o in observations:
        g = group_key(o)
        if g is None:
            continue
        for w in WINDOWS:
            r = o["returns"].get(w)
            if r is not None:
                by_group[g][w].append(r)

    out: dict[str, dict] = {}
    for g, wmap in by_group.items():
        entry: dict[str, dict | int] = {}
        for w in WINDOWS:
            arr = wmap.get(w, [])
            if not arr:
                entry[w] = None
                continue
            entry[w] = {
                "n": len(arr),
                "mean": round(statistics.mean(arr), 5),
                "median": round(statistics.median(arr), 5),
                "win_rate": round(sum(1 for x in arr if x > 0) / len(arr), 3),
                "p_max": round(max(arr), 5),
                "p_min": round(min(arr), 5),
            }
        # n_total: 윈도우 무관 관측 수
        entry["n_observations"] = sum(len(v) for v in wmap.values())
        out[g] = entry
    return out


def fmt_table(group_label: str, agg: dict, sort_window: str = "30d", min_obs: int = MIN_OBS_FOR_DISPLAY) -> str:
    """group → markdown table. n>=min_obs만. sort_window 평균 내림차순."""
    rows = []
    for g, entry in agg.items():
        e30 = entry.get(sort_window)
        if not e30 or e30["n"] < min_obs:
            continue
        rows.append((g, entry))
    if not rows:
        return f"### {group_label}\n\n_(관측 부족 — n ≥ {min_obs}만 표시)_\n"

    rows.sort(key=lambda x: -(x[1].get(sort_window, {}) or {}).get("mean", 0))
    body = []
    body.append("| | n | 7d mean | 30d mean | 60d mean | 90d mean | 30d win | 30d med |")
    body.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for g, entry in rows[:30]:
        e7 = entry.get("7d") or {}
        e30 = entry.get("30d") or {}
        e60 = entry.get("60d") or {}
        e90 = entry.get("90d") or {}
        def pct(x):
            if x is None:
                return "—"
            return f"{x*100:+.1f}%"
        body.append(
            f"| {g[:40]} | {e30.get('n','—')} | {pct(e7.get('mean'))} | "
            f"{pct(e30.get('mean'))} | {pct(e60.get('mean'))} | {pct(e90.get('mean'))} | "
            f"{e30.get('win_rate','—')} | {pct(e30.get('median'))} |"
        )
    suffix = ""
    if len(rows) > 30:
        suffix = f"\n\n_총 {len(rows)}개 그룹 중 상위 30 (30d mean 정렬)_"
    return f"### {group_label}\n\n" + "\n".join(body) + suffix + "\n"


def overall(observations: list[dict]) -> dict:
    """전체 통계."""
    agg: dict[str, list[float]] = defaultdict(list)
    for o in observations:
        for w in WINDOWS:
            r = o["returns"].get(w)
            if r is not None:
                agg[w].append(r)
    out = {}
    for w in WINDOWS:
        arr = agg[w]
        if not arr:
            out[w] = None
            continue
        out[w] = {
            "n": len(arr),
            "mean": round(statistics.mean(arr), 5),
            "median": round(statistics.median(arr), 5),
            "win_rate": round(sum(1 for x in arr if x > 0) / len(arr), 3),
        }
    return out


def main():
    if not INPUT_PATH.exists():
        print(f"[scorecard] {INPUT_PATH} 없음 — forward_validator 먼저")
        return
    payload = json.loads(INPUT_PATH.read_text())
    obs = payload.get("observations", [])
    print(f"[scorecard] observations: {len(obs)}")

    score = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "n_observations": len(obs),
        "overall": overall(obs),
        "by_channel": aggregate(obs, lambda o: o.get("channel")),
        "by_event_type": aggregate(obs, lambda o: o.get("event_type")),
        "by_canonical_theme": {},  # 필요 시 후처리
        "by_market": aggregate(obs, lambda o: o.get("market")),
    }
    # signals (테마 하나당 여러 signal)
    by_signal_obs: list[dict] = []
    for o in obs:
        for s in o.get("signals", []):
            n = dict(o)
            n["_signal"] = s
            by_signal_obs.append(n)
    score["by_signal"] = aggregate(by_signal_obs, lambda o: o.get("_signal"))

    # canonical theme: theme_dictionary 매핑
    dict_path = COMPILED / "theme_dictionary.json"
    canon_map: dict[str, str] = {}
    if dict_path.exists():
        try:
            d = json.loads(dict_path.read_text())
            for canon, info in d.get("canonical_themes", {}).items():
                for a in info.get("aliases", []):
                    canon_map[a] = canon
        except Exception:
            pass
    score["by_canonical_theme"] = aggregate(
        obs,
        lambda o: canon_map.get(o.get("theme_name", ""))
    )

    OUT_JSON.write_text(json.dumps(score, ensure_ascii=False, indent=2))
    print(f"[scorecard] → {OUT_JSON}")

    # Markdown 보고서
    OUT_MD.parent.mkdir(parents=True, exist_ok=True)
    md = []
    md.append(f"""---
type: scorecard
last_updated: {datetime.now().date()}
tags: [validation, scorecard, auto]
---

# Forward Returns Scorecard

> 추출 시점 종가 기준, calendar 기반 7/30/60/90일 후 종가 수익률.
> 자동 갱신 — `{datetime.now().isoformat(timespec='seconds')}` · 관측 {len(obs)}건

## Overall

""")
    o = score["overall"]
    md.append("| 윈도우 | n | mean | median | win_rate |")
    md.append("|---|---:|---:|---:|---:|")
    for w in WINDOWS:
        e = o.get(w) or {}
        if e:
            md.append(f"| {w} | {e['n']} | {e['mean']*100:+.2f}% | "
                      f"{e['median']*100:+.2f}% | {e['win_rate']:.2%} |")
    md.append("")

    md.append(fmt_table("By Channel", score["by_channel"]))
    md.append(fmt_table("By Event Type", score["by_event_type"]))
    md.append(fmt_table("By Market", score["by_market"], min_obs=10))
    md.append(fmt_table("By Signal (Top discovery_signals)", score["by_signal"], min_obs=20))
    md.append(fmt_table("By Canonical Theme (Top)", score["by_canonical_theme"], min_obs=8))

    OUT_MD.write_text("\n".join(md))
    print(f"[scorecard] → {OUT_MD}")


if __name__ == "__main__":
    main()
