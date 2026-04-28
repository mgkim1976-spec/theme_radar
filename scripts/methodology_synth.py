"""methodology_synth — 채널별 메소돌로지 패턴 LLM 합성.

흐름:
  1. 채널별 추출 로드 → high-conviction 테마(상위 50개) + signals 빈도 집계
  2. gpt-5.4-nano에 채널 프로파일과 샘플을 전달 → 5-bullet 메소돌로지 패턴 요약
  3. methodologies/{channel}_pattern.md 의 AUTO 블록 갱신

빈도 게이트 (--force 없으면):
  - 페이지가 7일 이내 갱신됐으면 스킵 (mtime 기준)

비용: 4채널 × ~$0.05 ≈ 주당 $0.2
"""
import json
import os
import statistics
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CHANNELS, EXTRACTION_MODEL, VAULT, COMPILED, channel_paths

METHODOLOGIES = VAULT / "methodologies"
AUTO_START = "<!-- METHODOLOGY_AUTO_START -->"
AUTO_END = "<!-- METHODOLOGY_AUTO_END -->"
STALE_DAYS = 7
MAX_SAMPLES = 50


def load_channel_data(subdir: str) -> dict | None:
    ext_dir = channel_paths(subdir)["extractions"]
    if not ext_dir.exists():
        return None
    samples = []
    signal_counter: Counter = Counter()
    primary_counter: Counter = Counter()
    style_flags: Counter = Counter()
    convictions: list[int] = []
    for f in sorted(ext_dir.glob("*_gpt-5.4-nano.json")):
        try:
            e = json.loads(f.read_text())
        except Exception:
            continue
        for t in e.get("themes", []):
            for s in t.get("discovery_signals", []):
                signal_counter[s] += 1
            if isinstance(t.get("conviction"), (int, float)):
                convictions.append(int(t["conviction"]))
            samples.append({
                "name": (t.get("name") or "")[:80],
                "stance": t.get("stance"),
                "conviction": t.get("conviction"),
                "rationale": (t.get("rationale") or "")[:200],
                "signals": t.get("discovery_signals", []),
                "date": f.name[:8],
            })
        mm = e.get("methodology_meta", {})
        for ps in mm.get("primary_signals", []):
            primary_counter[ps] += 1
        for k in ["uses_macro_top_down", "uses_news_driven",
                  "uses_chart_technical", "mentions_foreign_flows"]:
            if mm.get(k):
                style_flags[k] += 1

    if not samples:
        return None

    samples.sort(key=lambda x: -(x.get("conviction") or 0))
    return {
        "subdir": subdir,
        "n_videos": len({s["date"] for s in samples}),
        "n_themes": len(samples),
        "avg_conviction": round(statistics.mean(convictions), 2) if convictions else None,
        "signals_top10": signal_counter.most_common(10),
        "primary_top5": primary_counter.most_common(5),
        "style_flags": dict(style_flags),
        "samples_top": samples[:MAX_SAMPLES],
    }


def _load_channel_scorecard(subdir: str) -> dict:
    """Loop D: forward returns 채널별 통계 주입용."""
    sc_path = COMPILED / "scorecard.json"
    if not sc_path.exists():
        return {}
    try:
        sc = json.loads(sc_path.read_text())
    except Exception:
        return {}
    return (sc.get("by_channel") or {}).get(subdir) or {}


def build_prompt(ch_meta: dict, ch_data: dict, subdir: str) -> str:
    samples_block = "\n".join(
        f"- [{s['date']}] [{s['stance']}|conv={s['conviction']}] {s['name']} :: signals={','.join(s['signals'])}"
        for s in ch_data["samples_top"][:30]
    )
    signals_str = ", ".join(f"{k}({v})" for k, v in ch_data["signals_top10"])
    primary_str = ", ".join(f"{k}({v})" for k, v in ch_data["primary_top5"])
    style_str = ", ".join(f"{k}={v}" for k, v in ch_data["style_flags"].items())

    # Loop D: forward returns 메타 주입 (alpha 우선)
    sc_entry = _load_channel_scorecard(subdir)
    forward_block = ""
    if sc_entry:
        rows = []
        for w in ("7d", "30d", "60d", "90d"):
            e = sc_entry.get(w)
            if e:
                n = e.get("n_alpha") or e.get("n", "?")
                raw = e.get("mean", 0) * 100
                alpha = (e.get("mean_alpha") or 0) * 100
                win_a = (e.get("win_rate_alpha") or 0)
                rows.append(
                    f"  {w}: n={n} raw={raw:+.2f}% "
                    f"alpha(vs index)={alpha:+.2f}% alpha_win_rate={win_a:.1%}"
                )
        if rows:
            forward_block = (
                "\n# Forward Validation (실측 가격 피드백)\n"
                "  alpha = ticker_return - benchmark_return (KRX→KOSPI ETF, US→SPY)\n"
                "  alpha 양수면 시장 대비 outperform, 음수면 underperform.\n"
                "  raw return은 시기 효과(시장 베타) 포함이라 채널 비교에 부적합.\n\n"
                + "\n".join(rows)
            )

    return f"""당신은 한국 투자 유튜브 채널의 메소돌로지를 분석하는 애널리스트입니다.

# 채널 프로파일
- 이름: {ch_meta.get('name')}
- 스타일 라벨: {ch_meta.get('style')}
- 분석 영상 수: {ch_data['n_videos']} · 추출 테마 수: {ch_data['n_themes']}
- 평균 conviction: {ch_data['avg_conviction']}

# 신호 빈도 (Top 10)
{signals_str}

# 주요 신호 (primary, Top 5)
{primary_str}

# 추론 스타일 플래그
{style_str}
{forward_block}

# High-conviction 테마 샘플 (최대 30개)
{samples_block}

# 작업
이 채널의 **투자 메소돌로지 패턴**을 5–7개 핵심 bullet로 요약하세요. 각 bullet은:
1. 패턴 이름 (한 줄, 굵게)
2. 어떤 신호 조합으로 테마를 발굴하는지 (구체적인 signal 이름 인용)
3. 대표 사례 1개 (실제 샘플에서 인용)

추가로 마지막에:
- **차별화 포인트**: 다른 채널과 구분되는 1–2 문장
- **약점/사각지대**: 이 메소돌로지가 놓치기 쉬운 1문장
- **데이터 검증** (Forward Validation 데이터가 있을 때만): **α (시장 대비 alpha)** 를 우선 인용해
  메소돌로지의 어떤 부분이 *진짜 alpha*를 만드는지 / *시장 베타에 묻혔는지* / *시장보다 못 하는지*
  를 1-2 문장으로 명시. raw return은 시기 효과 포함이므로 신뢰 낮음. α 음수면 "시장 따라가기보다도
  못 했다" 솔직히 명시.

마크다운으로 출력하세요. 헤더(#)는 사용하지 말고 bullet과 강조만 사용."""


from llm_client import chat as llm_chat

ANALYST_SYSTEM = "당신은 한국 투자 유튜브 채널의 메소돌로지를 분석하는 시니어 애널리스트입니다."


def call_llm(prompt: str, model: str = EXTRACTION_MODEL) -> tuple[str, dict]:
    r = llm_chat(ANALYST_SYSTEM, prompt, model=model)
    return r.text, r.as_meta()


def upsert_methodology_page(subdir: str, ch_meta: dict, ch_data: dict, body: str, meta: dict):
    METHODOLOGIES.mkdir(parents=True, exist_ok=True)
    page = METHODOLOGIES / f"{subdir}_pattern.md"
    auto_block = f"""{AUTO_START}
**최근 갱신**: {datetime.now().isoformat(timespec='seconds')}
- 분석 영상: **{ch_data['n_videos']}** · 테마: **{ch_data['n_themes']}**
- LLM: {EXTRACTION_MODEL} · cost ${meta['cost_usd']}
- 신호 Top 5: {', '.join(f'`{k}`({v})' for k, v in ch_data['signals_top10'][:5])}

{body.strip()}
{AUTO_END}"""

    if page.exists():
        existing = page.read_text()
        if AUTO_START in existing and AUTO_END in existing:
            head = existing.split(AUTO_START)[0]
            tail = existing.split(AUTO_END)[1]
            page.write_text(head + auto_block + tail)
            return "updated"
        else:
            page.write_text(existing.rstrip() + "\n\n## 자동 합성\n\n" + auto_block + "\n")
            return "appended"
    else:
        page.write_text(f"""---
type: methodology
channel: {subdir}
name: {ch_meta.get('name')}
style: {ch_meta.get('style')}
last_updated: {datetime.now().date()}
tags: [methodology, auto-synth]
---

# {ch_meta.get('name')} — Methodology Pattern

{auto_block}
""")
        return "created"


def is_stale(subdir: str) -> bool:
    page = METHODOLOGIES / f"{subdir}_pattern.md"
    if not page.exists():
        return True
    age = datetime.now() - datetime.fromtimestamp(page.stat().st_mtime)
    return age >= timedelta(days=STALE_DAYS)


def main():
    force = "--force" in sys.argv
    only = None
    for a in sys.argv[1:]:
        if a.startswith("--channel="):
            only = a.split("=", 1)[1]

    if "OPENAI_API_KEY" not in os.environ:
        print("[methodology_synth] OPENAI_API_KEY 미설정 — 스킵")
        return

    total_cost = 0.0
    n_done = 0
    for subdir, ch_meta in CHANNELS.items():
        if only and subdir != only:
            continue
        if not force and not is_stale(subdir):
            print(f"[methodology_synth] {subdir}: ≤{STALE_DAYS}일 전 갱신 — 스킵")
            continue
        ch_data = load_channel_data(subdir)
        if not ch_data or ch_data["n_themes"] < 5:
            print(f"[methodology_synth] {subdir}: 데이터 부족 — 스킵")
            continue
        prompt = build_prompt(ch_meta, ch_data, subdir)
        try:
            body, meta = call_llm(prompt)
        except Exception as ex:
            print(f"[methodology_synth] {subdir}: LLM 호출 실패 — {ex}")
            continue
        action = upsert_methodology_page(subdir, ch_meta, ch_data, body, meta)
        total_cost += meta["cost_usd"]
        n_done += 1
        print(f"[methodology_synth] {subdir}: {action} (cost=${meta['cost_usd']})")
    print(f"[methodology_synth] done — {n_done} channels, total ${round(total_cost, 4)}")


if __name__ == "__main__":
    main()
