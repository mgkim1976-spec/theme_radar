"""comparative_synth — 4채널 cross-comparison LLM 자동 합성.

methodology_synth가 채널별 *독립* 합성이라면 이 모듈은 *비교*에 특화.

흐름:
  1. 모든 채널의 신호 빈도 + 라이프사이클별 lens 효과 + canonical 테마 분포 집계
  2. 채널 간 차이를 표·% 비교로 LLM에 전달
  3. 4 채널 한 번에 비교하는 5-7 bullet 메소돌로지 비교 보고서 생성
  4. methodologies/comparative_overview.md 의 AUTO 블록 갱신

게이트: 7일 이내 갱신됐으면 스킵 (--force 로 우회)
비용: 1회 호출, ~$0.005
"""
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CHANNELS, COMPILED, VAULT, channel_paths
from llm_client import chat as llm_chat, DEFAULT_MODEL

OUT_PATH = VAULT / "methodologies" / "comparative_overview.md"
DICT_PATH = COMPILED / "theme_dictionary.json"
AUTO_START = "<!-- COMPARATIVE_AUTO_START -->"
AUTO_END = "<!-- COMPARATIVE_AUTO_END -->"
STALE_DAYS = 7


def load_alias_to_canon() -> dict[str, str]:
    if not DICT_PATH.exists():
        return {}
    try:
        d = json.loads(DICT_PATH.read_text())
    except Exception:
        return {}
    out: dict[str, str] = {}
    for canon, info in d.get("canonical_themes", {}).items():
        for a in info.get("aliases", []):
            out[a] = canon
    return out


def collect_channel_profile(subdir: str, alias_to_canon: dict) -> dict | None:
    ext_dir = channel_paths(subdir)["extractions"]
    if not ext_dir.exists():
        return None
    n_videos = 0
    n_themes = 0
    signals: Counter = Counter()
    style: Counter = Counter()
    canon_counter: Counter = Counter()
    convs: list[int] = []
    dates: list[str] = []
    for f in sorted(ext_dir.glob("*_gpt-5.4-nano.json")):
        try:
            e = json.loads(f.read_text())
        except Exception:
            continue
        n_videos += 1
        dates.append(f.name[:8])
        for t in e.get("themes", []):
            n_themes += 1
            for s in t.get("discovery_signals", []):
                signals[s] += 1
            if isinstance(t.get("conviction"), (int, float)):
                convs.append(int(t["conviction"]))
            raw = (t.get("name") or "").strip()
            canon = alias_to_canon.get(raw) or raw[:30]
            if canon:
                canon_counter[canon] += 1
        mm = e.get("methodology_meta", {})
        for k in ["uses_macro_top_down", "uses_news_driven",
                  "uses_chart_technical", "mentions_foreign_flows"]:
            if mm.get(k):
                style[k] += 1
    if n_videos == 0:
        return None
    total_sig = sum(signals.values()) or 1
    return {
        "subdir": subdir,
        "n_videos": n_videos,
        "n_themes": n_themes,
        "date_range": f"{min(dates)[:6]} ~ {max(dates)[:6]}" if dates else "",
        "avg_conviction": round(sum(convs) / len(convs), 2) if convs else None,
        "signals_pct": {s: round(c / total_sig * 100, 1) for s, c in signals.most_common(12)},
        "style_pct": {k: round(v / n_videos * 100, 1) for k, v in style.items()},
        "themes_top10": canon_counter.most_common(10),
    }


def build_prompt(profiles: list[dict]) -> str:
    """4채널 비교 프롬프트."""
    rows = []
    for p in profiles:
        meta = CHANNELS.get(p["subdir"], {})
        rows.append({
            "channel": p["subdir"],
            "name": meta.get("name"),
            "lens": meta.get("lens"),
            "stock_weight": meta.get("stock_weight"),
            "n_videos": p["n_videos"],
            "n_themes": p["n_themes"],
            "date_range": p["date_range"],
            "avg_conviction": p["avg_conviction"],
            "signals_pct_top12": p["signals_pct"],
            "style_pct": p["style_pct"],
            "themes_top10": p["themes_top10"],
        })
    body = json.dumps(rows, ensure_ascii=False, indent=2)
    return f"""다음은 한국 투자 유튜브 채널 4개의 추출 데이터 통계입니다.

{body}

# 작업
4채널 메소돌로지를 **비교**하는 보고서를 한국어 마크다운으로 작성하세요.
구성:

## 1. 한 줄 요약
각 채널을 lens 관점에서 한 문장으로 (예: "86번가는 정책-공시 기반 pre-emergence hunter").

## 2. 신호 빈도 비교 (표)
4채널 모두 Top 5에 들어가는 공통 신호 + 한 채널만 강한 신호 표시.

## 3. 추론 스타일 비교 (표)
top-down, news-driven, chart, foreign_flows 4개 boolean 비율을 채널별로.

## 4. 단골 테마 — 겹침 여부
각 채널 Top 10 테마에서 (a) 4채널 공통 (b) 2-3채널 공유 (c) 단독을 분류.

## 5. lens별 사각지대
각 채널이 *놓치는* 영역을 1-2문장으로.

## 6. 통합 활용 가이드
"X 신호가 Y 채널에서만 잡히면 → Z 단계 행동" 식 의사결정 규칙 3-5개.

헤더는 ##만 사용. 각 표는 markdown table. 통계 인용 시 정확한 % 사용."""


def is_stale() -> bool:
    if not OUT_PATH.exists():
        return True
    age = datetime.now() - datetime.fromtimestamp(OUT_PATH.stat().st_mtime)
    return age >= timedelta(days=STALE_DAYS)


def upsert(body: str, meta: dict, profiles: list[dict]):
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    auto = f"""{AUTO_START}
> 자동 합성 — `{datetime.now().isoformat(timespec='seconds')}`
> 데이터: {sum(p['n_videos'] for p in profiles)} 영상, {sum(p['n_themes'] for p in profiles)} 테마, {len(profiles)} 채널
> LLM: {DEFAULT_MODEL} · cost ${meta['cost_usd']}

{body.strip()}
{AUTO_END}"""

    if OUT_PATH.exists():
        existing = OUT_PATH.read_text()
        if AUTO_START in existing and AUTO_END in existing:
            head = existing.split(AUTO_START)[0]
            tail = existing.split(AUTO_END)[1]
            OUT_PATH.write_text(head + auto + tail)
            return "updated"
        else:
            # 기존 수동 페이지 보존, AUTO 블록 append
            OUT_PATH.write_text(existing.rstrip() + "\n\n## 자동 비교 합성\n\n" + auto + "\n")
            return "appended"
    else:
        OUT_PATH.write_text(f"""---
type: methodology
applies_to: channel_comparison
last_updated: {datetime.now().date()}
tags: [methodology, comparison, multi-channel, auto-synth]
---

# 채널별 비교 개요

{auto}
""")
        return "created"


def main():
    force = "--force" in sys.argv
    if not force and not is_stale():
        print(f"[comparative_synth] ≤{STALE_DAYS}일 전 갱신 — 스킵 (--force 로 우회)")
        return

    alias_to_canon = load_alias_to_canon()
    profiles = []
    for subdir in CHANNELS:
        p = collect_channel_profile(subdir, alias_to_canon)
        if p:
            profiles.append(p)
    if len(profiles) < 2:
        print(f"[comparative_synth] 채널 < 2개 — 비교 의미 없음")
        return

    prompt = build_prompt(profiles)
    try:
        r = llm_chat(
            "당신은 여러 투자 메소돌로지를 데이터 기반으로 비교하는 시니어 애널리스트입니다.",
            prompt,
        )
    except Exception as ex:
        print(f"[comparative_synth] LLM 호출 실패 — {ex}")
        return
    action = upsert(r.text, r.as_meta(), profiles)
    print(f"[comparative_synth] {action} ({len(profiles)} 채널 비교, cost=${round(r.cost_usd, 5)})")


if __name__ == "__main__":
    main()
