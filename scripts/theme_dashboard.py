"""theme_dashboard — 신규·가속·소멸·콘센서스 검출.

룰베이스 (LLM 미사용):
  - 신규(Emerging)   : first_mention ≤ 7일 전
  - 가속(Accelerating): n7 / max(n30 - n7, 1) ≥ 3.0
  - 소멸(Fading)     : last_mention ≥ 45일 전 + 이전 ≥ 3 mentions
  - 콘센서스(Consensus): 14일 내 ≥ 2개 채널 동시 언급

출력:
  - VAULT/themes/_dashboard.md  (전체 대시보드)
  - VAULT/index.md 의 'WEEKLY_PULSE' 섹션 갱신

데이터 윈도우는 today(=시스템 일자) 기준. 채널 자체의 마지막 업로드와 무관.
"""
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CHANNELS, COMPILED, VAULT, channel_paths
import lifecycle as lc

DICT_PATH = COMPILED / "theme_dictionary.json"
DASH_PATH = VAULT / "themes" / "_dashboard.md"
DASH_JSON_PATH = COMPILED / "dashboard_signals.json"
INDEX_PATH = VAULT / "index.md"
TODAY = datetime.now().date()
PULSE_START = "<!-- WEEKLY_PULSE_START -->"
PULSE_END = "<!-- WEEKLY_PULSE_END -->"


def parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except Exception:
        return None


def collect_canon_occurrences(d: dict) -> dict[str, list[dict]]:
    """canonical_name → occurrences."""
    alias_to_canon = {}
    for canon, info in d["canonical_themes"].items():
        for a in info["aliases"]:
            alias_to_canon[a] = canon
    out: dict[str, list[dict]] = defaultdict(list)
    for subdir in CHANNELS:
        ext_dir = channel_paths(subdir)["extractions"]
        if not ext_dir.exists():
            continue
        for f in sorted(ext_dir.glob("*_gpt-5.4-nano.json")):
            try:
                e = json.loads(f.read_text())
            except Exception:
                continue
            upload_date = parse_date(f.name[:8])
            if not upload_date:
                continue
            for t in e.get("themes", []):
                name = (t.get("name") or "").strip()
                canon = alias_to_canon.get(name)
                if not canon:
                    continue
                out[canon].append({
                    "channel": subdir,
                    "date": upload_date,
                })
    return out


def detect_signals(canon_occs: dict[str, list[dict]], d: dict, thresholds: dict) -> dict:
    """4개 시그널 카테고리 → {category: [(canon, info, metric)]}.

    임계값:
      - emerging: 첫 언급 ≤ thresholds['emerging_window']/2 (대시보드는 더 타이트)
      - fading:   마지막 언급 ≥ thresholds['fading_threshold']
      - 가속/콘센서스: 7일/14일 윈도우 (단순 보조 시그널이라 정적 유지)
    """
    em_window = max(7, thresholds["emerging_window"] // 2)
    fade_thresh = thresholds["fading_threshold"]
    cutoff_em = TODAY - timedelta(days=em_window)
    cutoff7 = TODAY - timedelta(days=7)
    cutoff14 = TODAY - timedelta(days=14)
    cutoff30 = TODAY - timedelta(days=30)

    emerging = []
    accelerating = []
    fading = []
    consensus = []

    for canon, occs in canon_occs.items():
        if not occs:
            continue
        info = d["canonical_themes"].get(canon, {})
        dates = sorted(o["date"] for o in occs)
        first = dates[0]
        last = dates[-1]
        n7 = sum(1 for d in dates if d >= cutoff7)
        n14 = sum(1 for d in dates if d >= cutoff14)
        n30 = sum(1 for d in dates if d >= cutoff30)

        # 신규
        if first >= cutoff_em and n7 >= 1:
            emerging.append((canon, info, {"first": first, "n7": n7}))

        # 가속
        if n7 >= 2 and (n7 / max(n30 - n7, 1)) >= 3.0:
            accelerating.append((canon, info, {"n7": n7, "n30": n30, "ratio": round(n7 / max(n30 - n7, 1), 2)}))

        # 소멸 (이전엔 활성, 현재 무언급)
        if (TODAY - last).days >= fade_thresh and len(occs) >= 3:
            fading.append((canon, info, {"last": last, "n_total": len(occs)}))

        # 콘센서스
        recent14_channels = {o["channel"] for o in occs if o["date"] >= cutoff14}
        if len(recent14_channels) >= 2:
            consensus.append((canon, info, {"channels_14d": sorted(recent14_channels), "n14": n14}))

    # 정렬
    emerging.sort(key=lambda x: -x[2]["n7"])
    accelerating.sort(key=lambda x: -x[2]["ratio"])
    fading.sort(key=lambda x: -x[2]["n_total"])
    consensus.sort(key=lambda x: (-len(x[2]["channels_14d"]), -x[2]["n14"]))

    return {
        "emerging": emerging,
        "accelerating": accelerating,
        "fading": fading,
        "consensus": consensus,
    }


def fmt_section(title: str, items: list, fmt_one) -> str:
    if not items:
        return f"### {title}\n\n_(없음)_\n"
    body = "\n".join(fmt_one(canon, info, m) for canon, info, m in items[:20])
    suffix = f"\n\n_총 {len(items)}건 중 상위 20건._" if len(items) > 20 else ""
    return f"### {title} ({len(items)})\n\n{body}{suffix}\n"


def render_dashboard(signals: dict) -> str:
    f_emerge = lambda c, i, m: (
        f"- [[themes/{i.get('slug', '')}|{c}]] · 첫 언급 `{m['first']}` · 7일 {m['n7']}회"
    )
    f_accel = lambda c, i, m: (
        f"- [[themes/{i.get('slug', '')}|{c}]] · 7d/이전 30d 비율 **{m['ratio']}** ({m['n7']}/{m['n30']-m['n7']})"
    )
    f_fade = lambda c, i, m: (
        f"- [[themes/{i.get('slug', '')}|{c}]] · 마지막 언급 `{m['last']}` · 누적 {m['n_total']}회"
    )
    f_cons = lambda c, i, m: (
        f"- [[themes/{i.get('slug', '')}|{c}]] · {len(m['channels_14d'])}채널 · "
        f"{', '.join(m['channels_14d'])} (14일 {m['n14']}회)"
    )
    sections = (
        fmt_section("🆕 Emerging — 신규 등장", signals["emerging"], f_emerge)
        + "\n"
        + fmt_section("🚀 Accelerating — 가속", signals["accelerating"], f_accel)
        + "\n"
        + fmt_section("🤝 Consensus — 채널 합의", signals["consensus"], f_cons)
        + "\n"
        + fmt_section("📉 Fading — 소멸", signals["fading"], f_fade)
    )
    header = f"""---
type: dashboard
last_updated: {TODAY}
tags: [dashboard, auto-ingested]
---

# Theme Dashboard

> 자동 갱신 — `{datetime.now().isoformat(timespec='seconds')}`
> 윈도우 기준일: {TODAY} · 데이터: {sum(len(s) for s in signals.values())} signals total

"""
    return header + sections


def update_index_pulse(signals: dict):
    """index.md 의 WEEKLY_PULSE 섹션만 갱신/추가."""
    short = (
        f"### Weekly Theme Pulse — {TODAY}\n\n"
        f"- 🆕 Emerging: **{len(signals['emerging'])}**\n"
        f"- 🚀 Accelerating: **{len(signals['accelerating'])}**\n"
        f"- 🤝 Consensus: **{len(signals['consensus'])}**\n"
        f"- 📉 Fading: **{len(signals['fading'])}**\n\n"
        f"→ 상세: [[themes/_dashboard]]\n"
    )
    block = f"{PULSE_START}\n{short}{PULSE_END}"

    if INDEX_PATH.exists():
        content = INDEX_PATH.read_text()
        if PULSE_START in content and PULSE_END in content:
            head = content.split(PULSE_START)[0]
            tail = content.split(PULSE_END)[1]
            INDEX_PATH.write_text(head + block + tail)
        else:
            INDEX_PATH.write_text(content.rstrip() + "\n\n" + block + "\n")
    else:
        INDEX_PATH.write_text(f"# theme_radar — index\n\n{block}\n")


def main():
    if not DICT_PATH.exists():
        print("[theme_dashboard] theme_dictionary.json 없음 — theme_normalizer 먼저 실행")
        return
    d = json.loads(DICT_PATH.read_text())
    canon_occs = collect_canon_occurrences(d)

    # lifecycle 임계값 — theme_pages_gen이 캐시한 값을 재사용 (없으면 즉석 계산)
    thresholds = lc.load_cache()
    if thresholds.get("mode") != "data-driven":
        canon_dates = [sorted(o["date"] for o in occs) for occs in canon_occs.values() if occs]
        thresholds = lc.compute_thresholds(canon_dates, today=TODAY)
    print(f"[theme_dashboard] using thresholds: emerging/2≤{thresholds['emerging_window']//2}d, "
          f"fading≥{thresholds['fading_threshold']}d")
    signals = detect_signals(canon_occs, d, thresholds)

    DASH_PATH.parent.mkdir(parents=True, exist_ok=True)
    DASH_PATH.write_text(render_dashboard(signals))
    update_index_pulse(signals)

    # daily_digest 가 사용할 machine-readable JSON 도 함께 생성
    COMPILED.mkdir(parents=True, exist_ok=True)
    json_signals = {}
    for cat in ("emerging", "accelerating", "consensus", "fading"):
        items = []
        for canon, info, m in signals[cat]:
            entry = {"canonical": canon, "slug": info.get("slug")}
            for k, v in m.items():
                # date 객체 → ISO 문자열
                if hasattr(v, "isoformat"):
                    entry[k] = v.isoformat()
                else:
                    entry[k] = v
            items.append(entry)
        json_signals[cat] = items
    DASH_JSON_PATH.write_text(json.dumps({
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": TODAY.isoformat(),
        "signals": json_signals,
    }, ensure_ascii=False, indent=2))

    print(
        f"[theme_dashboard] emerging={len(signals['emerging'])} "
        f"accel={len(signals['accelerating'])} "
        f"consensus={len(signals['consensus'])} "
        f"fading={len(signals['fading'])}"
    )


if __name__ == "__main__":
    main()
