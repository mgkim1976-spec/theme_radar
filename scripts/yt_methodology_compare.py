"""Comparative methodology analysis across multiple YouTubers.

Reads extraction_v2 JSONs from multiple channel directories and produces:
- Side-by-side signal usage patterns
- Common vs differentiated themes
- Methodology meta comparison
- Policy/diplomatic event coverage comparison
- Time normalization (per-period analysis + market regime overlay)
- Per-channel ranked report
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

# === Market regime mapping (시장 환경 라벨) ===
# Date ranges → regime label
MARKET_REGIMES = [
    # (start_yyyymm, end_yyyymm, label)
    ("202003", "202012", "코로나_급반등_강세장"),
    ("202101", "202112", "유동성_강세장"),
    ("202201", "202210", "Fed_긴축_약세장"),
    ("202211", "202304", "약세장_바닥_횡보"),
    ("202305", "202312", "AI_반등_강세장"),
    ("202401", "202412", "AI_확장_강세장"),
    ("202501", "202509", "강세장_지속"),
    ("202510", "202604", "K_랠리_강세장"),
]

def get_regime(yyyymmdd: str) -> str:
    yyyymm = yyyymmdd[:6]
    for start, end, label in MARKET_REGIMES:
        if start <= yyyymm <= end:
            return label
    return "미분류"

def get_quarter(yyyymmdd: str) -> str:
    y, m = yyyymmdd[:4], int(yyyymmdd[4:6])
    q = (m - 1) // 3 + 1
    return f"{y}Q{q}"

# Channels to compare (display_name, channel_subdir)
CHANNELS = [
    ("한균수",  "han_gyunsoo"),
    ("86번가",  "86bunga"),
    # Future: ("서재형", "seo_jaehyung"), ("김일구", "kim_ilgu"), ("김현준", "kim_hyunjun"),
]

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from config import YOUTUBE_DATA
BASE = YOUTUBE_DATA
OUT = BASE / "COMPARATIVE_METHODOLOGY.md"

def load_channel(subdir):
    d = BASE / subdir / "extractions_v2"
    if not d.exists():
        return []
    out = []
    for f in sorted(d.glob("*_gpt-5.4-nano.json")):
        e = json.loads(f.read_text())
        # Inject upload_date from filename (YYYYMMDD_videoid.json)
        e["_meta"]["upload_date"] = f.name[:8]
        e["_meta"]["regime"] = get_regime(f.name[:8])
        e["_meta"]["quarter"] = get_quarter(f.name[:8])
        out.append(e)
    return out

# === Theme normalization (shared with yt_methodology.py) ===
def normalize_theme(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["원전", "전력", "전기", "에너지", "유틸리티"]):
        return "원전·전력설비"
    if any(k in n for k in ["2차전지", "배터리", "양극재", "음극재"]):
        return "2차전지"
    if any(k in n for k in ["바이오", "제약", "신약"]):
        return "바이오·제약"
    if any(k in n for k in ["반도체", "메모리", "hbm", "파운드리", "후공정"]):
        return "반도체"
    if any(k in n for k in ["로봇", "휴머노이드"]):
        return "로봇·휴머노이드"
    if any(k in n for k in ["조선", "방산", "함정", "엔진"]):
        return "조선·방산"
    if any(k in n for k in ["호텔", "면세", "여행", "카지노", "관광"]):
        return "여행·소비재"
    if any(k in n for k in ["원자재", "구리", "금", "은"]):
        return "원자재"
    if any(k in n for k in ["ai", "인공지능", "데이터센터"]):
        return "AI·데이터센터"
    if any(k in n for k in ["화장품", "k-뷰티", "뷰티"]):
        return "화장품·K뷰티"
    if any(k in n for k in ["엔터", "콘텐츠", "게임"]):
        return "엔터·플랫폼"
    if any(k in n for k in ["환율", "원달러", "달러"]):
        return "환율"
    if any(k in n for k in ["채권", "국채", "금리"]):
        return "채권·금리"
    if any(k in n for k in ["fomc", "연준", "fed"]):
        return "Fed/FOMC"
    if any(k in n for k in ["인플레", "물가", "cpi"]):
        return "인플레·물가"
    if any(k in n for k in ["고용", "실업"]):
        return "고용·실업"
    if any(k in n for k in ["원유", "유가", "opec"]):
        return "원유·OPEC"
    return "기타"


def analyze_channel(extractions):
    """Per-channel metrics. Includes time-bucketed views."""
    if not extractions:
        return None
    n = len(extractions)
    signal_count = Counter()
    primary_signal = Counter()
    theme_count = Counter()
    theme_stance = defaultdict(Counter)
    theme_signals = defaultdict(Counter)
    ticker_count = Counter()
    policy_count = Counter()
    policy_sectors = defaultdict(Counter)
    methodology = Counter()
    total_themes = 0

    # Time-bucketed
    by_regime = defaultdict(lambda: {"n": 0, "signals": Counter(), "themes": Counter()})
    by_quarter = defaultdict(lambda: {"n": 0, "signals": Counter()})
    date_range = {"min": "99999999", "max": "00000000"}

    for e in extractions:
        upload_date = e["_meta"].get("upload_date", "00000000")
        regime = e["_meta"].get("regime", "미분류")
        quarter = e["_meta"].get("quarter", "?")
        date_range["min"] = min(date_range["min"], upload_date)
        date_range["max"] = max(date_range["max"], upload_date)
        by_regime[regime]["n"] += 1
        by_quarter[quarter]["n"] += 1

        for t in e.get("themes", []):
            total_themes += 1
            cat = normalize_theme(t["name"])
            theme_count[cat] += 1
            theme_stance[cat][t["stance"]] += 1
            by_regime[regime]["themes"][cat] += 1
            for s in t["discovery_signals"]:
                signal_count[s] += 1
                theme_signals[cat][s] += 1
                by_regime[regime]["signals"][s] += 1
                by_quarter[quarter]["signals"][s] += 1
            for tk in t.get("tickers_normalized", []):
                if tk.get("status") in ("exact", "fuzzy"):
                    ticker_count[tk["name"]] += 1
                elif tk.get("status") == "foreign":
                    ticker_count[tk["name"]] += 1
        for p in e.get("policy_diplomatic_mentions", []):
            policy_count[p["event_type"]] += 1
            for sec in p.get("expected_impact_sectors", []):
                policy_sectors[p["event_type"]][sec] += 1
        mm = e.get("methodology_meta", {})
        for ps in mm.get("primary_signals", []):
            primary_signal[ps] += 1
        if mm.get("uses_macro_top_down"):
            methodology["top_down"] += 1
        if mm.get("uses_news_driven"):
            methodology["news"] += 1
        if mm.get("uses_chart_technical"):
            methodology["chart"] += 1
        if mm.get("mentions_foreign_flows"):
            methodology["foreign"] += 1

    return {
        "n": n,
        "total_themes": total_themes,
        "signal_count": signal_count,
        "primary_signal": primary_signal,
        "theme_count": theme_count,
        "theme_stance": theme_stance,
        "theme_signals": theme_signals,
        "ticker_count": ticker_count,
        "policy_count": policy_count,
        "policy_sectors": policy_sectors,
        "methodology": methodology,
        "by_regime": dict(by_regime),
        "by_quarter": dict(by_quarter),
        "date_range": date_range,
    }


def render():
    channels_data = []
    for display, subdir in CHANNELS:
        ext = load_channel(subdir)
        analysis = analyze_channel(ext)
        if analysis:
            channels_data.append((display, subdir, analysis))
            print(f"  {display}: {analysis['n']} videos, {analysis['total_themes']} themes")
        else:
            print(f"  {display}: NO DATA")

    if not channels_data:
        print("No channel data found.")
        return

    out = []
    out.append("# 멀티채널 메소돌로지 비교 보고서")
    out.append("")
    out.append("| 채널 | 영상 수 | 추출 테마 | 분석 기간 |")
    out.append("|---|---:|---:|---|")
    for d, sub, a in channels_data:
        dr = a["date_range"]
        period = f"{dr['min'][:4]}-{dr['min'][4:6]} ~ {dr['max'][:4]}-{dr['max'][4:6]}"
        out.append(f"| {d} | {a['n']} | {a['total_themes']} | {period} |")
    out.append("")

    # === 1. Discovery signal usage comparison ===
    out.append("## 1. 발굴 신호 사용 비교 (테마-신호 빈도)")
    out.append("")
    all_signals = set()
    for _, _, a in channels_data:
        all_signals.update(a["signal_count"].keys())
    all_signals = sorted(all_signals)

    header = "| 신호 | " + " | ".join(d for d, _, _ in channels_data) + " |"
    sep = "|---|" + "---:|" * len(channels_data)
    out.append(header)
    out.append(sep)
    for sig in sorted(all_signals,
                      key=lambda s: -sum(a["signal_count"].get(s, 0)
                                          for _, _, a in channels_data)):
        cells = []
        for d, _, a in channels_data:
            cnt = a["signal_count"].get(sig, 0)
            total = a["total_themes"]
            pct = (cnt / total * 100) if total else 0
            cells.append(f"{cnt} ({pct:.0f}%)")
        out.append(f"| {sig} | " + " | ".join(cells) + " |")
    out.append("")

    # === 2. Methodology meta comparison ===
    out.append("## 2. 추론 스타일 메타 (영상 수 비율)")
    out.append("")
    out.append("| 스타일 | " + " | ".join(d for d, _, _ in channels_data) + " |")
    out.append("|---|" + "---:|" * len(channels_data))
    for key, label in [("top_down", "Top-down 거시"),
                       ("news", "News-driven"),
                       ("chart", "Chart/기술적"),
                       ("foreign", "외인·기관 자금흐름")]:
        cells = []
        for _, _, a in channels_data:
            v = a["methodology"].get(key, 0)
            n = a["n"]
            pct = (v / n * 100) if n else 0
            cells.append(f"{v}/{n} ({pct:.0f}%)")
        out.append(f"| {label} | " + " | ".join(cells) + " |")
    out.append("")

    # === 3. Theme coverage comparison ===
    out.append("## 3. 자주 다루는 테마 (Top 15) — 누가 무엇을 보는가")
    out.append("")
    all_themes = Counter()
    for _, _, a in channels_data:
        for t, c in a["theme_count"].items():
            all_themes[t] += c
    out.append("| 테마 | " + " | ".join(d for d, _, _ in channels_data) + " |")
    out.append("|---|" + "---:|" * len(channels_data))
    for theme, _ in all_themes.most_common(15):
        if theme == "기타":
            continue
        cells = []
        for _, _, a in channels_data:
            cnt = a["theme_count"].get(theme, 0)
            cells.append(str(cnt))
        out.append(f"| {theme} | " + " | ".join(cells) + " |")
    out.append("")

    # === 4. Channel signature (각 채널의 차별점) ===
    out.append("## 4. 채널별 시그니처 — 그 채널만의 특징")
    out.append("")
    for d, _, a in channels_data:
        out.append(f"### {d} ({a['n']}편)")
        # Top primary signals
        top_signals = a["primary_signal"].most_common(3)
        out.append(f"- **주력 신호 Top 3**: " + ", ".join(f"{s} ({c})" for s, c in top_signals))
        # Methodology profile
        styles = []
        for k, label in [("top_down", "Top-down"), ("news", "News"),
                         ("chart", "Chart"), ("foreign", "Foreign-flow")]:
            if a["methodology"].get(k, 0) > a["n"] * 0.5:
                styles.append(label)
        out.append(f"- **추론 스타일**: " + ", ".join(styles) if styles else "없음")
        # Top themes
        top_themes = [t for t, c in a["theme_count"].most_common(5) if t != "기타"][:3]
        out.append(f"- **단골 테마**: " + ", ".join(top_themes))
        # Top tickers
        top_tickers = [tk for tk, c in a["ticker_count"].most_common(5)]
        out.append(f"- **자주 언급 종목**: " + ", ".join(top_tickers[:5]))
        # Policy/Diplomatic
        total_policy = sum(a["policy_count"].values())
        out.append(f"- **정책/외교 감지**: 영상당 {total_policy/a['n']:.1f}건")
        out.append("")

    # === 5. Policy event coverage ===
    out.append("## 5. 정책/외교 이벤트 감지력 비교")
    out.append("")
    all_events = set()
    for _, _, a in channels_data:
        all_events.update(a["policy_count"].keys())
    out.append("| 이벤트 타입 | " + " | ".join(d for d, _, _ in channels_data) + " |")
    out.append("|---|" + "---:|" * len(channels_data))
    for event in sorted(all_events,
                       key=lambda e: -sum(a["policy_count"].get(e, 0)
                                           for _, _, a in channels_data)):
        if event == "기타":
            continue
        cells = []
        for _, _, a in channels_data:
            cnt = a["policy_count"].get(event, 0)
            n = a["n"]
            per_video = cnt / n if n else 0
            cells.append(f"{cnt} ({per_video:.2f}/편)")
        out.append(f"| {event} | " + " | ".join(cells) + " |")
    out.append("")

    # === 6. Common ground / Differentiation ===
    out.append("## 6. 공통점 vs 차별점")
    out.append("")
    if len(channels_data) >= 2:
        # Themes covered by ALL vs only one
        each_themes = []
        for _, _, a in channels_data:
            each_themes.append(set(t for t, c in a["theme_count"].items()
                                    if c >= a["n"] * 0.05 and t != "기타"))  # at least 5% of videos
        common = set.intersection(*each_themes) if each_themes else set()
        out.append(f"### 모든 채널이 다루는 공통 테마 ({len(common)}개)")
        for t in sorted(common):
            counts = ", ".join(f"{d}:{a['theme_count'].get(t, 0)}"
                               for d, _, a in channels_data)
            out.append(f"- **{t}** ({counts})")
        out.append("")
        for i, (d, _, a) in enumerate(channels_data):
            others = set()
            for j, (_, _, oa) in enumerate(channels_data):
                if i != j:
                    others.update(t for t, c in oa["theme_count"].items()
                                  if c >= oa["n"] * 0.05 and t != "기타")
            unique = each_themes[i] - others
            if unique:
                out.append(f"### {d}만 다루는 차별 테마 ({len(unique)}개)")
                for t in sorted(unique, key=lambda x: -a["theme_count"][x])[:8]:
                    out.append(f"- **{t}** ({a['theme_count'][t]}편)")
                out.append("")

    # === 7. 시장 환경별 신호 사용 (시간 정규화) ===
    out.append("## 7. 시간 정규화: 시장 환경별 신호 사용 패턴")
    out.append("")
    out.append("각 채널이 어떤 시장 환경에서 활동했는지, 환경별로 신호 사용이 어떻게 달랐는지 비교.")
    out.append("")
    out.append("### 7-1. 환경별 영상 분포")
    out.append("")
    all_regimes = set()
    for _, _, a in channels_data:
        all_regimes.update(a["by_regime"].keys())
    out.append("| 시장 환경 | " + " | ".join(d for d, _, _ in channels_data) + " |")
    out.append("|---|" + "---:|" * len(channels_data))
    for regime in [r[2] for r in MARKET_REGIMES]:
        if regime not in all_regimes:
            continue
        cells = []
        for _, _, a in channels_data:
            cnt = a["by_regime"].get(regime, {"n": 0})["n"]
            pct = cnt / a["n"] * 100 if a["n"] else 0
            cells.append(f"{cnt} ({pct:.0f}%)")
        out.append(f"| {regime} | " + " | ".join(cells) + " |")
    out.append("")

    # === 7-2. Top signals per regime per channel ===
    out.append("### 7-2. 환경별 Top 신호 (각 채널 내 비중)")
    out.append("")
    for d, _, a in channels_data:
        out.append(f"#### {d}")
        for regime in [r[2] for r in MARKET_REGIMES]:
            r_data = a["by_regime"].get(regime)
            if not r_data or r_data["n"] == 0:
                continue
            top3 = r_data["signals"].most_common(3)
            sig_str = ", ".join(f"{s}({c})" for s, c in top3)
            out.append(f"- **{regime}** ({r_data['n']}편): {sig_str}")
        out.append("")

    # === 7-3. 분기별 영상 수 (시계열 안정성) ===
    out.append("### 7-3. 분기별 영상 분포 (활동 시계열)")
    out.append("")
    all_quarters = sorted({q for _, _, a in channels_data for q in a["by_quarter"]})
    out.append("| 분기 | " + " | ".join(d for d, _, _ in channels_data) + " |")
    out.append("|---|" + "---:|" * len(channels_data))
    for q in all_quarters:
        cells = []
        any_data = False
        for _, _, a in channels_data:
            cnt = a["by_quarter"].get(q, {"n": 0})["n"]
            cells.append(str(cnt) if cnt else "-")
            if cnt:
                any_data = True
        if any_data:
            out.append(f"| {q} | " + " | ".join(cells) + " |")
    out.append("")

    # === 7-4. 메소돌로지 안정성 (한 채널 내 시기별 신호 변동) ===
    out.append("### 7-4. 채널별 메소돌로지 안정성 (시기 변해도 신호 비중이 일관되는가)")
    out.append("")
    for d, _, a in channels_data:
        if len(a["by_regime"]) < 2:
            out.append(f"- **{d}**: 단일 시장 환경 ({list(a['by_regime'].keys())[0]}) — 안정성 측정 불가")
            continue
        # Compute coefficient of variation for top 5 signals across regimes
        top_signals = [s for s, _ in a["signal_count"].most_common(5)]
        out.append(f"- **{d}**: 환경별 Top 5 신호 비중 변동")
        for sig in top_signals:
            ratios = []
            for regime, r_data in a["by_regime"].items():
                if r_data["n"] == 0:
                    continue
                total_signals_in_regime = sum(r_data["signals"].values())
                if total_signals_in_regime == 0:
                    continue
                ratio = r_data["signals"].get(sig, 0) / total_signals_in_regime * 100
                ratios.append((regime, ratio))
            if len(ratios) >= 2:
                ratio_str = " | ".join(f"{r:.0f}%" for _, r in ratios[:6])
                avg = sum(r for _, r in ratios) / len(ratios)
                out.append(f"  - {sig}: {ratio_str} (avg {avg:.1f}%)")
        out.append("")

    # === 8. Key insight summary ===
    out.append("## 8. 핵심 인사이트 (자동 도출)")
    out.append("")
    for d, _, a in channels_data:
        n = a["n"]
        top_sig = a["signal_count"].most_common(1)[0] if a["signal_count"] else ("?", 0)
        macro_pct = a["methodology"].get("top_down", 0) / n * 100 if n else 0
        chart_pct = a["methodology"].get("chart", 0) / n * 100 if n else 0
        policy_per = sum(a["policy_count"].values()) / n if n else 0
        style_summary = "매크로 중심" if macro_pct >= 70 else (
                        "차트 중심" if chart_pct >= 60 else "혼합형")
        out.append(f"- **{d}**: {style_summary}, 주력신호={top_sig[0]}, 정책감지={policy_per:.1f}/편")
    out.append("")

    OUT.write_text("\n".join(out))
    print(f"\nSaved: {OUT}")
    print(f"Lines: {len(out)}")


if __name__ == "__main__":
    render()
