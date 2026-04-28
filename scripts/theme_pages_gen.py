"""theme_pages_gen — canonical theme별 themes/{slug}.md 자동 생성·갱신.

흐름:
  1. theme_dictionary.json 로드
  2. 모든 추출에서 alias 매칭 → 채널/날짜/conviction/signals/rationale 수집
  3. 라이프사이클 자동 분류 (룰베이스):
       Emerging   : first_seen ≤ 14일 전
       Confirming : 7일 이동평균 빈도↑ AND 채널수 ≥ 2
       Mature     : 90일 평균 빈도 안정 (≥3편/90d, std/mean < 1.0)
       Fading     : 마지막 언급 ≥ 30일 전
  4. themes/{slug}.md 의 AUTO_* 섹션만 갱신 (수동 작성 부분 보존)

LLM 미사용. 비용 0.
"""
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CHANNELS, COMPILED, VAULT, channel_paths
import lifecycle as lc

DICT_PATH = COMPILED / "theme_dictionary.json"
MATRIX_PATH = COMPILED / "theme_to_stock_matrix.json"
SCORECARD_PATH = COMPILED / "scorecard.json"
TODAY = datetime.now().date()


def load_dict() -> dict:
    if not DICT_PATH.exists():
        raise FileNotFoundError(
            f"{DICT_PATH} not found — run theme_normalizer.py first"
        )
    return json.loads(DICT_PATH.read_text())


def load_matrix() -> dict:
    """theme_to_stock_matrix.json (있으면)."""
    if not MATRIX_PATH.exists():
        return {}
    try:
        d = json.loads(MATRIX_PATH.read_text())
        return d.get("matrix", {})
    except Exception:
        return {}


def load_scorecard_themes() -> dict:
    """scorecard.json 의 by_canonical_theme 만 추출."""
    if not SCORECARD_PATH.exists():
        return {}
    try:
        d = json.loads(SCORECARD_PATH.read_text())
        return d.get("by_canonical_theme", {}) or {}
    except Exception:
        return {}


def load_event_taxonomies() -> dict:
    """macro + corporate event taxonomy + regime + phase 동시 로드."""
    out = {}
    for axis in ("macro", "corporate"):
        p = COMPILED / f"{axis}_event_taxonomy.json"
        if not p.exists():
            out[axis] = {}
            continue
        try:
            d = json.loads(p.read_text())
            out[axis] = d.get("themes", {})
        except Exception:
            out[axis] = {}
    # regime_alignment: theme → alignment 정보
    out["regime"] = {}
    out["regime_meta"] = {}
    rp = COMPILED / "regime_alignment.json"
    if rp.exists():
        try:
            r = json.loads(rp.read_text())
            out["regime"] = r.get("themes", {})
            out["regime_meta"] = {
                "current": r.get("current_regime"),
                "score": r.get("regime_score"),
                "confidence": r.get("regime_confidence"),
            }
        except Exception:
            pass
    # phase_mapping: macro_event_id → historical events
    out["phase"] = {}
    pp = COMPILED / "phase_mapping.json"
    if pp.exists():
        try:
            p = json.loads(pp.read_text())
            out["phase"] = p.get("mapping", {})
        except Exception:
            pass
    return out


def collect_occurrences() -> dict[str, list[dict]]:
    """{theme_name: [{channel, date, conviction, stance, signals, event_type, rationale, video_id}]}"""
    by_name: dict[str, list[dict]] = defaultdict(list)
    for subdir in CHANNELS:
        ext_dir = channel_paths(subdir)["extractions"]
        if not ext_dir.exists():
            continue
        for f in sorted(ext_dir.glob("*_gpt-5.4-nano.json")):
            try:
                e = json.loads(f.read_text())
            except Exception:
                continue
            upload_date = f.name[:8]
            video_id = e.get("_meta", {}).get("video_id", "")
            title = e.get("_meta", {}).get("title", "")
            for t in e.get("themes", []):
                name = (t.get("name") or "").strip()
                if not name:
                    continue
                by_name[name].append({
                    "channel": subdir,
                    "date": upload_date,
                    "conviction": t.get("conviction", 0),
                    "stance": t.get("stance", "neutral"),
                    "signals": t.get("discovery_signals", []),
                    "event_type": t.get("event_type"),
                    "rationale": (t.get("rationale") or "")[:300],
                    "video_id": video_id,
                    "title": title[:80],
                })
    return by_name


def parse_yyyymmdd(s: str):
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except Exception:
        return None


def classify_lifecycle(occs: list[dict], thresholds: dict) -> str:
    """동적 임계값 기반 lifecycle 라벨."""
    dates = sorted(d for d in (parse_yyyymmdd(o["date"]) for o in occs) if d)
    n_channels = len({o["channel"] for o in occs})
    return lc.classify(dates, n_channels, thresholds, today=TODAY)


AUTO_START = "<!-- THEME_AUTO_START -->"
AUTO_END = "<!-- THEME_AUTO_END -->"


def fmt_event_section(canon: str, taxonomies: dict) -> str:
    """macro + corporate event + regime alignment + phase 표시."""
    rows = []
    for axis, label in [("macro", "🌐 Macro"), ("corporate", "🏢 Corporate")]:
        entry = taxonomies.get(axis, {}).get(canon)
        if not entry:
            rows.append(f"- **{label}**: _(매칭 없음)_")
            continue
        ids = entry.get("matched_event_ids", [])[:3]
        conf = entry.get("confidence", "?")
        method = entry.get("method", "?")
        inh = entry.get("inherited", {}) or {}
        sev = inh.get("severity", "")
        direction = inh.get("direction", "")
        kw = entry.get("matching_keyword", "")
        meta = []
        if sev: meta.append(f"severity={sev}")
        if direction: meta.append(f"dir={direction}")
        meta_str = f" ({', '.join(meta)})" if meta else ""
        kw_str = f" · kw='{kw}'" if kw else ""
        rows.append(
            f"- **{label}**: `{', '.join(ids)}` · conf={conf}/{method}"
            f"{meta_str}{kw_str}"
        )

    # Regime alignment (macro 매칭이 있을 때만)
    regime_entry = taxonomies.get("regime", {}).get(canon)
    regime_meta = taxonomies.get("regime_meta", {})
    if regime_entry:
        cur = regime_meta.get("current", "?")
        align = regime_entry.get("alignment", "?")
        ctx = regime_entry.get("event_regime_context", "")[:80]
        emoji = {"aligned": "✅", "partial": "🟡", "misaligned": "🔴", "neutral": "⚪"}.get(align, "?")
        rows.append(f"- **🌡️ Regime**: 현재 `{cur}` · 적합도 {emoji} **{align}** "
                    f"({ctx if ctx else 'regime_context 없음'})")
    elif regime_meta.get("current"):
        rows.append(f"- **🌡️ Regime**: 현재 `{regime_meta['current']}` · _(macro 매칭 없어 적합도 미산출)_")

    # Phase 참고 (macro 매칭의 첫 event_id 기준)
    macro_entry = taxonomies.get("macro", {}).get(canon)
    if macro_entry:
        macro_ids = macro_entry.get("matched_event_ids", [])
        if macro_ids:
            phase_match = taxonomies.get("phase", {}).get(macro_ids[0], [])
            if phase_match:
                top = phase_match[0]
                rows.append(f"- **⏱️ 유사 historical**: `{top['historical_event_id']}` "
                            f"({top.get('date', '?')}, {top.get('category', '?')})")

    return "## Event Classification (multi-axis)\n\n" + "\n".join(rows) + "\n"


def fmt_validation_section(canon: str, scoreboard: dict) -> str:
    entry = scoreboard.get(canon)
    if not entry:
        return "## Forward Validation\n\n_(가격 데이터 부족 — 종목 매핑 또는 윈도우 미완료)_\n"
    rows = []
    for w in ("7d", "30d", "60d", "90d"):
        e = entry.get(w)
        if not e:
            continue
        n = e.get("n", e.get("n_alpha", "—"))
        mean_raw = (e.get("mean") or 0) * 100
        mean_a = (e.get("mean_alpha") or 0) * 100
        win = (e.get("win_rate") or 0)
        win_a = (e.get("win_rate_alpha") or 0)
        rows.append(
            f"| {w} | {n} | {mean_raw:+.1f}% | {win:.0%} | "
            f"**{mean_a:+.1f}%** | **{win_a:.0%}** |"
        )
    if not rows:
        return "## Forward Validation\n\n_(완료된 윈도우 없음)_\n"
    return (
        "## Forward Validation (가격 피드백, **α = vs 시장 인덱스**)\n\n"
        "| 윈도우 | n | raw | win | **α** | **α-win** |\n"
        "|---|---:|---:|---:|---:|---:|\n"
        + "\n".join(rows) + "\n"
    )


def fmt_ticker_section(canon: str, matrix: dict) -> str:
    entry = matrix.get(canon)
    if not entry or not entry.get("tickers"):
        return "## Top 관련 종목\n\n_(매트릭스 데이터 없음)_\n"
    rows = entry["tickers"][:10]
    body = "\n".join(
        f"| {i+1} | {t['name']} | {t['krx_status']} | {t['score']} | {t['n_mentions']} | "
        f"{', '.join(t['channels'])} | `{t.get('first','')}`–`{t.get('last','')}` |"
        for i, t in enumerate(rows)
    )
    return (
        "## Top 10 관련 종목 (theme×stock 매트릭스)\n\n"
        "| # | 종목 | KRX | score | 언급수 | 채널 | 최초–최근 |\n"
        "|---:|---|---|---:|---:|---|---|\n"
        + body + "\n"
    )


def render_page(canon: str, info: dict, occs: list[dict], matrix: dict,
                thresholds: dict, scoreboard: dict, taxonomies: dict) -> str:
    """전체 페이지 (frontmatter + AUTO 블록만 — 수동 작성 부분은 별도)."""
    lifecycle = classify_lifecycle(occs, thresholds)
    dates = sorted(d for d in (parse_yyyymmdd(o["date"]) for o in occs) if d)
    first = dates[0].isoformat() if dates else "?"
    last = dates[-1].isoformat() if dates else "?"
    by_channel: dict[str, int] = defaultdict(int)
    signal_counts: dict[str, int] = defaultdict(int)
    event_counts: dict[str, int] = defaultdict(int)
    convictions: list[int] = []
    stances: dict[str, int] = defaultdict(int)
    for o in occs:
        by_channel[o["channel"]] += 1
        for s in o["signals"]:
            signal_counts[s] += 1
        ev = o.get("event_type")
        if ev:
            event_counts[ev] += 1
        if isinstance(o.get("conviction"), (int, float)):
            convictions.append(int(o["conviction"]))
        stances[o.get("stance", "neutral")] += 1

    avg_conv = round(statistics.mean(convictions), 2) if convictions else None
    top_signals = sorted(signal_counts.items(), key=lambda x: -x[1])[:8]
    top_events = sorted(event_counts.items(), key=lambda x: -x[1])[:6]
    top_rationales = sorted(
        occs, key=lambda o: -(o.get("conviction") or 0)
    )[:3]

    front = f"""---
type: theme
canonical_name: {canon}
slug: {info['slug']}
aliases: {json.dumps(info['aliases'], ensure_ascii=False)}
lifecycle: {lifecycle}
first_seen: {first}
last_seen: {last}
total_mentions: {info['total_mentions']}
channels: {json.dumps(info['channels'], ensure_ascii=False)}
last_updated: {TODAY}
tags: [theme, auto-ingested, lifecycle-{lifecycle.lower()}]
---

# {canon}

"""

    ticker_block = fmt_ticker_section(canon, matrix)
    validation_block = fmt_validation_section(canon, scoreboard)
    event_block = fmt_event_section(canon, taxonomies)

    auto = f"""{AUTO_START}
**최근 갱신**: {datetime.now().isoformat(timespec='seconds')}

## 라이프사이클: **{lifecycle}**

- 최초 언급: `{first}` · 최근 언급: `{last}`
- 총 언급: **{info['total_mentions']}** 회 · 평균 conviction: {avg_conv if avg_conv is not None else 'N/A'}
- 채널: {', '.join(f'[[youtubers/{c}]]' for c in info['channels'])}
- 입장 분포: """ + ", ".join(f"{k}={v}" for k, v in stances.items()) + f"""

## 채널별 언급

| 채널 | 횟수 |
|---|---:|
""" + "\n".join(f"| {c} | {n} |" for c, n in sorted(by_channel.items(), key=lambda x: -x[1])) + f"""

## Top 8 발굴 신호

| 신호 | 빈도 |
|---|---:|
""" + "\n".join(f"| {s} | {n} |" for s, n in top_signals) + f"""

## 카탈리스트 이벤트 타입 (event_type)

""" + ("| 타입 | 빈도 |\n|---|---:|\n" + "\n".join(f"| {ev} | {n} |" for ev, n in top_events) if top_events else "_(데이터 없음 — 구 스키마 추출)_") + f"""

{event_block}
{validation_block}
{ticker_block}
## Top 3 Rationale (high-conviction)

""" + "\n\n".join(
        f"**{o['date']} · {o['channel']} · conv={o['conviction']}** — {o['title']}\n> {o['rationale']}"
        for o in top_rationales
    ) + f"""

## Aliases

{', '.join(f'`{a}`' for a in info['aliases'][:15])}{' …' if len(info['aliases']) > 15 else ''}
{AUTO_END}"""

    return front + auto + "\n"


def upsert_theme_page(canon: str, info: dict, occs: list[dict], matrix: dict,
                      thresholds: dict, scoreboard: dict, taxonomies: dict) -> str:
    page = VAULT / "themes" / f"{info['slug']}.md"
    page.parent.mkdir(parents=True, exist_ok=True)

    rendered = render_page(canon, info, occs, matrix, thresholds, scoreboard, taxonomies)

    if page.exists():
        existing = page.read_text()
        if AUTO_START in existing and AUTO_END in existing:
            # AUTO 블록만 교체
            head = existing.split(AUTO_START)[0]
            tail = existing.split(AUTO_END)[1] if AUTO_END in existing else ""
            new_auto = rendered.split(AUTO_START)[1].split(AUTO_END)[0]
            page.write_text(head + AUTO_START + new_auto + AUTO_END + tail)
            return "updated"
        else:
            # 수동 페이지가 있는데 AUTO 블록이 없음 → AUTO 블록만 append
            new_auto = rendered.split(AUTO_START)[1].split(AUTO_END)[0]
            page.write_text(
                existing.rstrip()
                + f"\n\n## Auto\n\n{AUTO_START}{new_auto}{AUTO_END}\n"
            )
            return "appended"
    else:
        page.write_text(rendered)
        return "created"


def main():
    d = load_dict()
    matrix = load_matrix()
    scoreboard = load_scorecard_themes()
    taxonomies = load_event_taxonomies()
    occurrences = collect_occurrences()

    # 동적 lifecycle 임계값 계산 (canonical theme별 dates 분포 기반)
    canon_dates_lists: list[list] = []
    alias_to_canon_local: dict[str, str] = {}
    for canon, info in d["canonical_themes"].items():
        for a in info["aliases"]:
            alias_to_canon_local[a] = canon
    canon_dates_map: dict[str, list] = {}
    for raw_name, rows in occurrences.items():
        canon = alias_to_canon_local.get(raw_name)
        if not canon:
            continue
        for r in rows:
            d_ = parse_yyyymmdd(r["date"])
            if d_:
                canon_dates_map.setdefault(canon, []).append(d_)
    canon_dates_lists = [sorted(v) for v in canon_dates_map.values() if v]
    thresholds = lc.compute_thresholds(canon_dates_lists, today=TODAY)
    lc.save_cache(thresholds)
    print(f"[theme_pages_gen] lifecycle thresholds: {thresholds.get('mode')} "
          f"(emerging≤{thresholds['emerging_window']}d, "
          f"fading≥{thresholds['fading_threshold']}d, "
          f"mature≥{thresholds['mature_min_age']}d)")

    # alias → canonical 룩업
    alias_to_canon: dict[str, str] = {}
    for canon, info in d["canonical_themes"].items():
        for a in info["aliases"]:
            alias_to_canon[a] = canon

    # canonical별 occurrence 합치기
    canon_occs: dict[str, list[dict]] = defaultdict(list)
    for raw_name, rows in occurrences.items():
        canon = alias_to_canon.get(raw_name)
        if not canon:
            continue
        canon_occs[canon].extend(rows)

    stats = {"created": 0, "updated": 0, "appended": 0, "skipped": 0}
    # 임계: 노이즈 줄이려 mentions ≥ 2만 페이지 생성
    for canon, info in d["canonical_themes"].items():
        if info["total_mentions"] < 2:
            stats["skipped"] += 1
            continue
        occs = canon_occs.get(canon, [])
        if not occs:
            stats["skipped"] += 1
            continue
        action = upsert_theme_page(canon, info, occs, matrix, thresholds, scoreboard, taxonomies)
        stats[action] += 1

    print(
        f"[theme_pages_gen] created={stats['created']} "
        f"updated={stats['updated']} appended={stats['appended']} "
        f"skipped={stats['skipped']}"
    )


if __name__ == "__main__":
    main()
