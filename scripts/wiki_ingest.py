"""theme_radar wiki ingest — 새 추출 결과 → wiki 페이지 자동 갱신.

기본 전략 (no LLM v1):
1. 각 채널의 youtubers/<channel>.md 페이지 통계 갱신 (재계산 후 덮어쓰기)
2. log.md에 ingest 기록 추가
3. catalysts/* 페이지 동기화 (catalysts.yaml 기반)

향후 v2 (LLM-based):
- themes/, companies/ 페이지 자동 발견·생성
- 새 wikilink 자동 연결
- 모순 탐지

v1는 가벼움·신뢰성 우선. LLM 안 씀 = 비용 0.
"""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import VAULT, YOUTUBE_DATA, CATALYSTS_YAML, CHANNELS, COMPILED, channel_paths


def _load_scorecard() -> dict:
    """data/reference/compiled/scorecard.json 로드 (있으면). by_channel 섹션만 사용."""
    p = COMPILED / "scorecard.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def _load_alias_to_canon() -> dict[str, str]:
    """theme_dictionary.json이 있으면 raw verbose name → canonical tag 매핑 반환."""
    p = COMPILED / "theme_dictionary.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
    except Exception:
        return {}
    out: dict[str, str] = {}
    for canon, info in d.get("canonical_themes", {}).items():
        for a in info.get("aliases", []):
            out[a] = canon
    return out


def load_extractions(subdir):
    d = channel_paths(subdir)["extractions"]
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*_gpt-5.4-nano.json")):
        try:
            e = json.loads(f.read_text())
            e["_meta"]["upload_date"] = f.name[:8]
            out.append(e)
        except Exception:
            continue
    return out


def compute_stats(extractions, alias_to_canon: dict[str, str] | None = None):
    n = len(extractions)
    if n == 0:
        return None
    alias_to_canon = alias_to_canon or {}
    signals = Counter()
    primary = Counter()
    themes = Counter()
    methodology = Counter()
    event_types = Counter()
    total_themes = 0
    dates = sorted(e["_meta"]["upload_date"] for e in extractions)
    for e in extractions:
        for t in e.get("themes", []):
            total_themes += 1
            raw = (t.get("name") or "").strip()
            # canonical tag로 집계 (사전 없으면 raw 30자 fallback)
            key = alias_to_canon.get(raw) or raw[:30]
            if key:
                themes[key] += 1
            for s in t.get("discovery_signals", []):
                signals[s] += 1
            ev = t.get("event_type")
            if ev:
                event_types[ev] += 1
        mm = e.get("methodology_meta", {})
        for ps in mm.get("primary_signals", []):
            primary[ps] += 1
        for k in ["uses_macro_top_down", "uses_news_driven", "uses_chart_technical", "mentions_foreign_flows"]:
            if mm.get(k):
                methodology[k] += 1
    return {
        "n": n,
        "total_themes": total_themes,
        "date_min": dates[0],
        "date_max": dates[-1],
        "signals_top10": signals.most_common(10),
        "primary_top5": primary.most_common(5),
        "methodology": dict(methodology),
        "themes_top10": themes.most_common(10),
        "event_types": event_types.most_common(),
        "forward_returns": None,  # main()에서 채널별 주입
    }


def update_youtuber_stats_section(channel_subdir, stats):
    """youtubers/{channel}.md 의 'Auto Stats' 섹션 갱신/추가."""
    page = VAULT / "youtubers" / f"{channel_subdir}.md"
    if not page.exists():
        # Skeleton 생성
        ch = CHANNELS.get(channel_subdir, {})
        page.write_text(f"""---
type: youtuber
name: {ch.get('name', channel_subdir)}
channel_id: {ch.get('channel_id', '')}
last_updated: {datetime.now().date()}
sources:
  - "~/MGPrj/theme_radar/data/youtube/{channel_subdir}/extractions_v2/"
tags: [youtuber, auto-ingested]
---

# {ch.get('name', channel_subdir)}

## Auto Stats

(아래 자동 갱신됨)

<!-- AUTO_STATS_START -->
<!-- AUTO_STATS_END -->
""")

    content = page.read_text()
    # Build new stats block
    auto_block = f"""<!-- AUTO_STATS_START -->
**최근 갱신**: {datetime.now().isoformat(timespec='seconds')}

- 영상 수: **{stats['n']}**
- 추출 테마: **{stats['total_themes']}**
- 기간: {stats['date_min'][:4]}-{stats['date_min'][4:6]} ~ {stats['date_max'][:4]}-{stats['date_max'][4:6]}

### Top 10 발굴 신호 (테마-신호 빈도)

| 신호 | 빈도 |
|---|---:|
""" + "\n".join(f"| {s} | {c} |" for s, c in stats['signals_top10']) + f"""

### 추론 스타일

- Top-down 거시: {stats['methodology'].get('uses_macro_top_down', 0)}/{stats['n']}
- News-driven: {stats['methodology'].get('uses_news_driven', 0)}/{stats['n']}
- Chart 기술적: {stats['methodology'].get('uses_chart_technical', 0)}/{stats['n']}
- 외인·자금흐름: {stats['methodology'].get('mentions_foreign_flows', 0)}/{stats['n']}

### Forward Validation (가격 피드백)

""" + (
    (lambda sc: (
        "| 윈도우 | n | mean | median | win |\n|---|---:|---:|---:|---:|\n" +
        "\n".join(
            f"| {w} | {sc.get(w, {}).get('n', '—')} | "
            f"{(sc.get(w, {}) or {}).get('mean', 0)*100:+.2f}% | "
            f"{(sc.get(w, {}) or {}).get('median', 0)*100:+.2f}% | "
            f"{(sc.get(w, {}) or {}).get('win_rate', 0):.1%} |"
            for w in ['7d', '30d', '60d', '90d']
            if sc.get(w)
        )
    ))(stats.get('forward_returns', {})) if stats.get('forward_returns') else "_(가격 데이터 부족 — pipeline stage 6 미완료)_"
) + """

### 카탈리스트 이벤트 타입 (event_type)

| 타입 | 빈도 |
|---|---:|
""" + ("\n".join(f"| {ev} | {n} ({round(n/max(stats['total_themes'],1)*100,1)}%) |" for ev, n in stats['event_types'][:8]) if stats['event_types'] else "_(데이터 없음)_") + """

### Top 10 테마 (canonical)

""" + "\n".join(f"- {t} ({c})" for t, c in stats['themes_top10']) + """
<!-- AUTO_STATS_END -->"""

    if "<!-- AUTO_STATS_START -->" in content:
        # Replace existing block
        before = content.split("<!-- AUTO_STATS_START -->")[0]
        after = content.split("<!-- AUTO_STATS_END -->")[1]
        content = before + auto_block + after
    else:
        # Append
        content += "\n\n## Auto Stats\n\n" + auto_block

    # Update last_updated frontmatter
    if "last_updated:" in content:
        import re
        content = re.sub(r"last_updated:.*", f"last_updated: {datetime.now().date()}", content)

    page.write_text(content)
    return True


def sync_catalysts():
    """catalysts.yaml의 youtube_extraction 항목들을 wiki에 동기화."""
    if not CATALYSTS_YAML.exists():
        return 0
    items = yaml.safe_load(CATALYSTS_YAML.read_text())
    yt_items = [c for c in items if c.get("source") == "youtube_extraction"]
    cat_dir = VAULT / "catalysts"
    cat_dir.mkdir(exist_ok=True)
    written = 0
    for c in yt_items:
        page = cat_dir / f"{c['id']}.md"
        if page.exists():
            continue  # Don't overwrite manually edited pages
        title = c.get('title', c['id'])
        actors = ", ".join(c.get('actors', []))
        assets = "\n".join(f"- [[companies/{a}]]" for a in c.get('affected_assets', []))
        sources = "\n".join(f"- {s}" for s in c.get('source_videos', []))
        page.write_text(f"""---
type: catalyst
date: {c.get('date')}
date_approx: {c.get('date_approx', False)}
category: {c.get('category')}
last_updated: {datetime.now().date()}
sources:
  - catalysts.yaml
tags: [catalyst, {c.get('category', 'other')}, auto-ingested]
---

# {title}

## 기본 정보

- **예정 날짜**: {c.get('date')} (date_approx: {c.get('date_approx')})
- **카테고리**: {c.get('category')}
- **참가자**: {actors}
- **출처**: youtube_extraction (자동 ingest)

## 출처 영상

{sources}

- **총 멘션**: {c.get('source_mentions', 0)}회
- **샘플 컨텍스트**: {c.get('source_label', '')}

## 영향 종목

{assets}

## 태그

{', '.join(c.get('tags', []))}

## Base Question

> {c.get('base_question', '')}

## 관련

- [[catalysts/index|catalysts 인덱스]]
""")
        written += 1
    return written


def append_log(updates):
    """log.md에 ingest 기록 추가."""
    log_file = VAULT / "log.md"
    if not log_file.exists():
        log_file.write_text("# Log\n\n")
    now = datetime.now().isoformat(timespec='seconds')
    entry = f"""
### {now} — INGEST (auto)
- Updated youtubers: {', '.join(updates['youtubers'])}
- Synced catalysts: {updates['catalysts_new']} new pages
- Source: pipeline.sh stage 5
"""
    content = log_file.read_text()
    # Insert after first H1
    if "\n## " in content:
        idx = content.find("\n## ")
        content = content[:idx] + entry + "\n" + content[idx:]
    else:
        content += entry
    log_file.write_text(content)


def main():
    print(f"[wiki_ingest] {datetime.now().isoformat()}")
    updates = {"youtubers": [], "catalysts_new": 0}

    alias_to_canon = _load_alias_to_canon()
    if alias_to_canon:
        print(f"  · canonical 매핑 로드됨 — {len(alias_to_canon)} aliases")
    scorecard = _load_scorecard()
    if scorecard:
        print(f"  · scorecard 로드됨 — {scorecard.get('n_observations', '?')} obs")

    # 1. Update each youtuber's stats
    for subdir in CHANNELS:
        extractions = load_extractions(subdir)
        if not extractions:
            print(f"  ⏩ {subdir}: no extractions")
            continue
        stats = compute_stats(extractions, alias_to_canon=alias_to_canon)
        if not stats:
            continue
        # forward returns 주입
        stats["forward_returns"] = (scorecard.get("by_channel") or {}).get(subdir)
        update_youtuber_stats_section(subdir, stats)
        updates["youtubers"].append(subdir)
        print(f"  ✓ {subdir}: {stats['n']} videos, {stats['total_themes']} themes")

    # 2. Sync catalysts
    new_catalysts = sync_catalysts()
    updates["catalysts_new"] = new_catalysts
    print(f"  ✓ catalysts: {new_catalysts} new pages")

    # 3. Log
    append_log(updates)
    print(f"  ✓ log.md updated")

    print(f"[wiki_ingest] done")


if __name__ == "__main__":
    main()
