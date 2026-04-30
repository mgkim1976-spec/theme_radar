"""daily_retail_alpha — 리테일 후킹 형식의 데일리 리포트, 단 과거 α 양수 픽만.

목적:
  daily_alpha_digest 가 raw picks 리스트라면, 이 모듈은 같은 데이터를 'Market Insight & Strategy'
  서사 형식으로 묶어 출력. 모든 표시 항목은 historical 30d 또는 90d median α > 0 통과해야 함.

5 섹션:
  1. 🌡️ Market Sentiment — 채널 overall_market_view 합성 (α 통과 테마만 가중)
  2. 🔥 Consensus — 2+ 채널 동일 canonical, 모두 bullish/watch
  3. ⚖️ Battleground — stance 분기, 또는 conviction 차이
  4. 💎 Unique Alpha — 1 채널, conviction>=4
  5. 📌 Action Plan — 단기 트레이딩 / 중기 스윙 / 장기 코어

출력: VAULT/today_retail.md (덮어쓰기) + VAULT/daily_retail/{date}.md (아카이브)

사용:
  python3 daily_retail_alpha.py                   # 기본 lookback=3
  python3 daily_retail_alpha.py --lookback 7
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import VAULT, COMPILED, CHANNELS, channel_paths

ALPHA_PATH = COMPILED / "alpha_lookups.json"
TD_PATH = COMPILED / "theme_dictionary.json"

OUT_PAGE = VAULT / "today_retail.md"
ARCHIVE_DIR = VAULT / "daily_retail"


def load_alias_to_canon() -> dict[str, str]:
    if not TD_PATH.exists():
        return {}
    td = json.loads(TD_PATH.read_text()).get("canonical_themes", {})
    out: dict[str, str] = {}
    for canon, info in td.items():
        out[canon] = canon
        for a in info.get("aliases", []):
            out[a] = canon
    return out


def expected_alpha(ch: str, signals: list, event_type: str, canon: str | None,
                   lookups: dict, window: str) -> tuple[float | None, str | None, int]:
    """positive max median α + source description."""
    cands = []
    by_cs = lookups.get("by_channel_signal", {})
    for sig in signals:
        s = by_cs.get(f"{ch}|{sig}", {}).get(window)
        if s and s["median"] is not None:
            cands.append((s["median"], f"{sig}", s["n"]))
    s = lookups.get("by_event_type", {}).get(event_type or "미해당", {}).get(window)
    if s and s["median"] is not None:
        cands.append((s["median"], f"evt:{event_type}", s["n"]))
    if canon:
        s = lookups.get("by_canonical", {}).get(canon, {}).get(window)
        if s and s["median"] is not None:
            cands.append((s["median"], f"canon:{canon}", s["n"]))
    if not cands:
        return None, None, 0
    best = max(cands, key=lambda c: c[0])
    return best[0], best[1], best[2]


def collect_themes(lookback_days: int, today: date, lookups: dict, alias_to_canon: dict) -> list[dict]:
    cutoff = today - timedelta(days=lookback_days)
    themes_out = []
    market_views: dict[str, list[str]] = defaultdict(list)  # channel → views
    catalysts_collect: list[tuple[str, str]] = []  # (channel, catalyst)
    warnings_collect: list[tuple[str, str]] = []

    for ch in CHANNELS:
        ext_dir = channel_paths(ch).get("extractions")
        if not ext_dir or not ext_dir.exists():
            continue
        files = sorted(ext_dir.glob("*.json"))
        # filter by date
        recent = [f for f in files if datetime.strptime(f.name[:8], "%Y%m%d").date() >= cutoff]
        for f in recent:
            try:
                d = json.loads(f.read_text())
            except Exception:
                continue
            d_date = f.name[:8]
            view = (d.get("overall_market_view") or "")[:300]
            if view:
                market_views[ch].append(view)
            for cat in d.get("key_catalysts", [])[:5]:
                catalysts_collect.append((ch, cat[:120]))
            for w in d.get("warnings", [])[:3]:
                warnings_collect.append((ch, w[:120]))
            for t in d.get("themes", []):
                tn = (t.get("name") or "").strip()
                if not tn:
                    continue
                signals = t.get("discovery_signals", []) or []
                event_type = t.get("event_type", "미해당")
                canon = alias_to_canon.get(tn)
                a30, src30, n30 = expected_alpha(ch, signals, event_type, canon, lookups, "30d")
                a90, src90, n90 = expected_alpha(ch, signals, event_type, canon, lookups, "90d")
                # filter: at least one positive
                if (a30 or 0) <= 0 and (a90 or 0) <= 0:
                    continue
                tickers_norm = t.get("tickers_normalized", []) or []
                ticker_names = []
                for tk in tickers_norm:
                    nm = tk.get("name") or tk.get("raw")
                    if nm: ticker_names.append(nm)
                if not ticker_names:
                    ticker_names = [x for x in (t.get("tickers", []) or []) if x][:4]
                themes_out.append({
                    "channel": ch,
                    "date": d_date,
                    "name": tn,
                    "canon": canon,
                    "stance": t.get("stance", "neutral"),
                    "conviction": int(t.get("conviction", 0) or 0),
                    "horizon": t.get("time_horizon", ""),
                    "signals": signals[:3],
                    "tickers": ticker_names[:5],
                    "rationale": (t.get("rationale") or "")[:200],
                    "alpha_30d": a30, "src_30d": src30, "n_30d": n30,
                    "alpha_90d": a90, "src_90d": src90, "n_90d": n90,
                    "consistent": (a30 or 0) > 0 and (a90 or 0) > 0,
                })
    return themes_out, market_views, catalysts_collect, warnings_collect


def group_themes(themes: list[dict]) -> dict:
    """consensus / battleground / niche 분류."""
    by_canon = defaultdict(list)
    for t in themes:
        key = t.get("canon") or t["name"][:40]
        by_canon[key].append(t)

    consensus = []   # ≥2 channels, all bullish/watch
    battleground = []  # 다른 stance 가 섞인 ≥2 channels
    niche = []  # 1 채널, conviction ≥ 4

    for key, items in by_canon.items():
        channels = {t["channel"] for t in items}
        stances = {t["stance"] for t in items}
        if len(channels) >= 2:
            # consensus if no bearish AND not heavily mixed
            if "bearish" not in stances:
                # all watch + bullish OK as consensus
                consensus.append((key, items))
            else:
                battleground.append((key, items))
        else:
            t = items[0]
            if t["conviction"] >= 4 and t["stance"] in ("bullish", "watch"):
                niche.append((key, items))

    # sort: consensus by best 90d α desc; niche by best 30d desc
    def best_alpha(items, w):
        return max((it.get(f"alpha_{w}") or 0) for it in items)

    consensus.sort(key=lambda kv: -best_alpha(kv[1], "90d"))
    battleground.sort(key=lambda kv: -best_alpha(kv[1], "30d"))
    niche.sort(key=lambda kv: -best_alpha(kv[1], "30d"))

    return {
        "consensus": consensus,
        "battleground": battleground,
        "niche": niche,
    }


def fmt_pct(x): return f"+{x*100:.1f}%" if x else "—"


PRETTY_REPLACEMENTS = [
    ("ai", "AI"), ("hbm", "HBM"), ("ev", "EV"), ("etf", "ETF"),
    ("oled", "OLED"), ("led", "LED"), ("cpu", "CPU"), ("gpu", "GPU"),
    ("smr", "SMR"), ("ess", "ESS"), ("sk", "SK"),
]


def pretty_name(s: str) -> str:
    """canonical snake_case 를 표시용으로 — 약어 대문자화 포함."""
    out = s.replace("_", " ").strip()
    parts = out.split(" ")
    new_parts = []
    for p in parts:
        lp = p.lower()
        replaced = False
        for src, dst in PRETTY_REPLACEMENTS:
            if lp == src:
                new_parts.append(dst)
                replaced = True
                break
        if not replaced:
            new_parts.append(p)
    return " ".join(new_parts)


def render_theme_block(name: str, items: list[dict]) -> str:
    """한 테마 블록 — 뉴스레터 톤, 채널/날짜/conviction 노출 없음."""
    all_tickers = []
    seen = set()
    for it in items:
        for tk in it["tickers"]:
            if tk not in seen:
                seen.add(tk)
                all_tickers.append(tk)
    tk_str = ", ".join(all_tickers[:6]) if all_tickers else None

    # 가장 충실한 rationale 1개 → 1~2 문장으로 압축, 시점 단어 normalize
    best_rationale = max(items, key=lambda x: len(x["rationale"]))["rationale"]
    snippet = neutralize_dates(best_rationale)
    for end in [".", "다.", "음.", "함.", "임."]:
        idx = snippet.find(end, 50)
        if 50 < idx < 180:
            snippet = snippet[: idx + len(end)]
            break
    snippet = snippet[:200].strip()

    stances = sorted({it["stance"] for it in items})
    is_bullish = "bullish" in stances and "bearish" not in stances
    tone = "**핵심 논리**" if is_bullish else "**투자 논리**"

    lines = [f"#### **{pretty_name(name)[:60]}**", ""]
    lines.append(f"{snippet}")
    if tk_str:
        lines.append("")
        lines.append(f"> **관련 종목:** {tk_str}")
    return "\n".join(lines) + "\n"


DATE_WORDS = [
    "월요일", "화요일", "수요일", "목요일", "금요일",
    "어제", "오늘", "지난주", "지난 주", "이번주", "이번 주",
    "전일", "당일", "오늘은", "어제는", "어제부터",
]


def neutralize_dates(text: str) -> str:
    """raw 텍스트의 요일·시점 표현을 일반화 — 발행일 기준 충돌 방지."""
    out = text
    # 조사 붙은 형태 먼저 처리 (긴 패턴 우선)
    replacements = [
        ("월요일은", "최근"), ("화요일은", "최근"), ("수요일은", "최근"),
        ("목요일은", "최근"), ("금요일은", "최근"),
        ("월요일에는", "최근"), ("화요일에는", "최근"), ("수요일에는", "최근"),
        ("목요일에는", "최근"), ("금요일에는", "최근"),
        ("월요일에", "최근"), ("화요일에", "최근"), ("수요일에", "최근"),
        ("목요일에", "최근"), ("금요일에", "최근"),
        ("월요일", "최근"), ("화요일", "최근"), ("수요일", "최근"),
        ("목요일", "최근"), ("금요일", "최근"),
        ("어제는", "최근"), ("어제부터", "최근"),
        ("오늘은", "최근"), ("오늘부터", "최근"),
        ("지난주는", "최근"), ("지난 주는", "최근"),
        ("지난주", "최근"), ("지난 주", "최근"),
        ("이번주는", "이번 주"), ("이번 주는", "이번 주"),
    ]
    for src, dst in replacements:
        out = out.replace(src, dst)
    while "최근 최근" in out:
        out = out.replace("최근 최근", "최근")
    return out


def render_market_temp(views: dict, warnings: list, themes_all: list[dict], today: date) -> str:
    """1. 시장 온도 — 오늘 발행 관점에서 narrative 합성."""
    # α 통과 테마 중 가장 빈번한 키워드 (영상 출처 텍스트가 아닌, 오늘 통과 테마 기반)
    from collections import Counter
    canon_counts = Counter()
    all_tickers_flat = []
    for t in themes_all:
        key = t.get("canon") or t["name"][:30]
        canon_counts[key] += 1
        for tk in t.get("tickers", []):
            all_tickers_flat.append(tk)
    top_themes = [pretty_name(c) for c, _ in canon_counts.most_common(3)]
    top_tickers = [tk for tk, _ in Counter(all_tickers_flat).most_common(5)]

    # 오늘 시점 헤드라인 1 문장 (data-driven, 출처 의존 없음)
    if top_themes:
        headline = (
            f"이번 주 시장은 **{', '.join(top_themes)}** 를 중심으로 흐름이 형성되고 있습니다."
        )
    else:
        headline = "이번 주는 시장 모멘텀이 분산된 구간입니다."

    # ticker 한 줄
    ticker_line = ""
    if top_tickers:
        ticker_line = f"가장 자주 거론된 종목은 **{', '.join(top_tickers[:5])}** 입니다."

    risks = [neutralize_dates(w) for _, w in warnings[:3]]

    txt = [
        "### **1. 🌡️ 시장 온도 (Market Sentiment)**",
        "",
        headline,
    ]
    if ticker_line:
        txt.append("")
        txt.append(ticker_line)
    if risks:
        txt.append("")
        txt.append("**이번 주 주의할 리스크**")
        for w in risks:
            txt.append(f"  - {w}")
    return "\n".join(txt) + "\n\n---\n"


def render_section(title: str, sub: str, groups: list[tuple], top_n: int, empty_msg: str) -> str:
    out = [f"### **{title}**", "", f"_{sub}_", ""]
    if not groups:
        out.append(empty_msg)
        return "\n".join(out) + "\n\n---\n"
    for key, items in groups[:top_n]:
        out.append(render_theme_block(key, items))
    return "\n".join(out) + "\n---\n"


def render_action_plan(themes_all: list[dict], today: date) -> str:
    """5. Action Plan — 단기/중기 분리, 뉴스레터 톤."""
    short = {}
    medium = {}
    for t in themes_all:
        key = t.get("canon") or t["name"][:40]
        if (t.get("alpha_30d") or 0) > 0:
            cur = short.get(key)
            if not cur or (t["alpha_30d"] > cur["alpha_30d"]):
                short[key] = t
        if (t.get("alpha_90d") or 0) > 0:
            cur = medium.get(key)
            if not cur or (t["alpha_90d"] > cur["alpha_90d"]):
                medium[key] = t

    short_sorted = sorted(short.items(), key=lambda kv: -(kv[1]["alpha_30d"] or 0))
    medium_sorted = sorted(medium.items(), key=lambda kv: -(kv[1]["alpha_90d"] or 0))

    def fmt_row(key: str, t: dict, window: str) -> str:
        a = t[f"alpha_{window}"] * 100
        tk = ", ".join(t["tickers"][:4]) if t["tickers"] else "_(개별 종목 미언급)_"
        return f"- **{pretty_name(key)[:30]}** _(과거 평균 +{a:.1f}%)_ — {tk}"

    plan = [
        "### **5. 📌 최종 행동 지침 (Action Plan)**",
        "",
        "**🚀 단기 매수 후보 (1주~1개월 호흡)**",
        "",
        "지난 데이터에서 비슷한 패턴이 1개월 안에 평균적으로 시장 대비 양호한 흐름을 보였던 테마입니다.",
        "",
    ]
    if short_sorted:
        for k, t in short_sorted[:6]:
            plan.append(fmt_row(k, t, "30d"))
    else:
        plan.append("_(오늘은 단기 진입 후보가 부족 — 관망 권장)_")
    plan.append("")
    plan.append("**🛤️ 중기 코어 후보 (3개월 호흡)**")
    plan.append("")
    plan.append("3개월 단위로 누적 시 시장 대비 양호한 성과 패턴이 누적된 테마입니다.")
    plan.append("")
    if medium_sorted:
        for k, t in medium_sorted[:6]:
            plan.append(fmt_row(k, t, "90d"))
    else:
        plan.append("_(오늘은 중기 진입 후보가 부족 — 관망 권장)_")
    plan.append("")
    plan.append("**💰 현금 관리**")
    plan.append("- 단일 종목 비중은 전체의 5~10% 이내")
    plan.append("- 변동성 구간에는 현금 비중 30% 이상 유지 권장")
    plan.append("- 위 후보는 과거 패턴 기반 참고 자료이며 미래 수익을 보장하지 않습니다")
    plan.append("")
    return "\n".join(plan) + "\n"


def render_one_liner(themes_all: list[dict]) -> str:
    """한 줄 요약 — 뉴스레터 마무리."""
    short_top = max(
        ((t for t in themes_all if (t.get("alpha_30d") or 0) > 0)),
        key=lambda t: t["alpha_30d"], default=None,
    )
    medium_top = max(
        ((t for t in themes_all if (t.get("alpha_90d") or 0) > 0)),
        key=lambda t: t["alpha_90d"], default=None,
    )
    parts = []
    if short_top:
        nm = pretty_name(short_top.get("canon") or short_top["name"][:25])
        parts.append(f"단기는 **{nm[:25]}**")
    if medium_top:
        nm = pretty_name(medium_top.get("canon") or medium_top["name"][:25])
        parts.append(f"중기는 **{nm[:25]}** 중심으로")
    if not parts:
        return "\n> **한 줄 요약:** 오늘은 진입 후보가 부족합니다. 관망 권장.\n"
    return f"\n> **한 줄 요약:** {' · '.join(parts)} 분할 매수 — 무리한 추격은 금물.\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=3)
    ap.add_argument("--top-consensus", type=int, default=5)
    ap.add_argument("--top-battleground", type=int, default=3)
    ap.add_argument("--top-niche", type=int, default=5)
    args = ap.parse_args()

    if not ALPHA_PATH.exists():
        print(f"[daily_retail_alpha] {ALPHA_PATH} 없음 — alpha_lookups.py 먼저 실행")
        return

    lookups = json.loads(ALPHA_PATH.read_text())
    alias_to_canon = load_alias_to_canon()
    today = date.today()

    themes, views, _, warnings = collect_themes(args.lookback, today, lookups, alias_to_canon)
    grouped = group_themes(themes)

    # total raw count for context
    cutoff = today - timedelta(days=args.lookback)
    total = 0
    for ch in CHANNELS:
        ext = channel_paths(ch).get("extractions")
        if not ext: continue
        for f in ext.glob("*.json"):
            d_str = f.name[:8]
            try:
                if datetime.strptime(d_str, "%Y%m%d").date() < cutoff: continue
            except ValueError: continue
            try:
                d = json.loads(f.read_text())
                total += len(d.get("themes", []))
            except Exception: pass

    KOR_DOW = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금", 5: "토", 6: "일"}
    dow = KOR_DOW.get(today.weekday(), "")
    head = (
        f"# 📊 {today.strftime('%Y.%m.%d')} ({dow}) Market Insight & Strategy\n\n"
        "> 시장에서 떠오르는 핵심 테마와 종목, 그리고 이번 주 행동 지침.\n\n"
        "---\n\n"
    )

    sect1 = render_market_temp(views, warnings, themes, today)
    sect2 = render_section(
        "2. 🔥 The Consensus (강력한 기회)",
        "여러 시각이 한 방향으로 모이는 핵심 섹터입니다.",
        grouped["consensus"], args.top_consensus,
        "_(오늘은 합의된 핵심 섹터가 뚜렷하지 않습니다 — 개별 테마 위주로 접근)_",
    )
    sect3 = render_section(
        "3. ⚖️ The Battleground (전략적 선택)",
        "투자 성향에 따라 진입 타이밍을 달리해야 할 승부처입니다.",
        grouped["battleground"], args.top_battleground,
        "_(오늘은 시장이 뚜렷한 분기점에 있지 않습니다)_",
    )
    sect4 = render_section(
        "4. 💎 Unique Alpha (틈새 전략)",
        "지수와 별개로 움직이는 개별 재료·정책 모멘텀 픽입니다.",
        grouped["niche"], args.top_niche,
        "_(오늘은 두드러지는 틈새 픽이 없습니다)_",
    )
    sect5 = render_action_plan(themes, today)
    one = render_one_liner(themes)

    page = head + sect1 + sect2 + sect3 + sect4 + sect5 + one

    OUT_PAGE.parent.mkdir(parents=True, exist_ok=True)
    OUT_PAGE.write_text(page)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (ARCHIVE_DIR / f"{today.isoformat()}.md").write_text(page)

    print(f"[daily_retail_alpha] α-passing themes: {len(themes)} / {total}")
    print(f"  consensus={len(grouped['consensus'])}, battleground={len(grouped['battleground'])}, niche={len(grouped['niche'])}")
    print(f"  → {OUT_PAGE}")


if __name__ == "__main__":
    main()
