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


def render_theme_block(name: str, items: list[dict]) -> str:
    """한 canonical theme 블록 — 채널명·출처 노출 없이 narrative 형식."""
    # 종목 합치기
    all_tickers = []
    seen = set()
    for it in items:
        for tk in it["tickers"]:
            if tk not in seen:
                seen.add(tk)
                all_tickers.append(tk)
    tk_str = ", ".join(all_tickers[:6]) if all_tickers else "—"

    stances = sorted({it["stance"] for it in items})
    convs = [it["conviction"] for it in items]
    conv_max = max(convs) if convs else 0

    # 가장 충실한 rationale 1개 (가장 긴 것)
    best_rationale = max(items, key=lambda x: len(x["rationale"]))["rationale"][:200]

    # 단기/중기 라벨
    has_30 = any((it.get("alpha_30d") or 0) > 0 for it in items)
    has_90 = any((it.get("alpha_90d") or 0) > 0 for it in items)
    if has_30 and has_90:
        tag = "단기·중기 모두 매칭"
    elif has_30:
        tag = "단기 매칭"
    elif has_90:
        tag = "중기 매칭"
    else:
        tag = ""

    stance_tone = ", ".join(stances)
    lines = [
        f"#### **{name[:60]}**",
        f"- **투자 논리:** {best_rationale}",
        f"- **관련 종목:** {tk_str}",
        f"- **시장 시각:** {stance_tone} (강도 {conv_max}/5){' · ' + tag if tag else ''}",
    ]
    return "\n".join(lines) + "\n"


def render_market_temp(views: dict, warnings: list, n_themes_passed: int, n_themes_total: int) -> str:
    """1. 시장 온도 — 채널명 노출 없이 시황·리스크 narrative 합성."""
    # 모든 view 모아 가장 긴 것 1~2개만 발췌 (출처 표시 없이)
    all_views = []
    for ch_views in views.values():
        all_views.extend(ch_views)
    all_views.sort(key=len, reverse=True)
    primary_view = (all_views[0][:280] + "…") if all_views else ""

    risks = [w for _, w in warnings[:3]]

    txt = [
        "### **1. 🌡️ 시장 온도 (Market Sentiment)**",
        "",
        f"> 최근 시장 흐름·리스크·기회 종합. 후속 Action Plan 은 historical α 양수 패턴 매칭 픽만 표시 ({n_themes_passed}/{n_themes_total} themes).",
        "",
    ]
    if primary_view:
        txt.append(f"**현재 시장:** {primary_view}")
        txt.append("")
    if risks:
        txt.append("**단기 리스크 (Short-term):**")
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
    """5. Action Plan — α 통과 픽만 단기/중기로 분리해 표시."""
    # 단기 = 30d α 양수 / 중기 = 90d α 양수 (양쪽에 모두 들어갈 수 있음)
    # canonical theme 단위로 dedup
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
        a = t[f"alpha_{window}"]
        n = t[f"n_{window}"]
        tk = ", ".join(t["tickers"][:4]) if t["tickers"] else "—"
        return (
            f"- **{key[:30]}** · expected α(과거 {window} median): **+{a*100:.1f}%** "
            f"(n={n}) · 종목: {tk}"
        )

    plan = [
        "### **5. 📌 최종 행동 지침 (Action Plan)**",
        "",
        "_과거 동일 패턴이 양수 α 를 만들었던 조합만 표시합니다. 같은 테마가 양쪽에 동시에 뜨면 가장 안정적인 픽._",
        "",
        f"#### **🚀 단기 (1주~1개월, 과거 30d α 양수) — {len(short_sorted)}건**",
        "",
    ]
    if short_sorted:
        for k, t in short_sorted[:8]:
            plan.append(fmt_row(k, t, "30d"))
    else:
        plan.append("_(오늘 통과 픽 없음 — 단기 트레이딩 자제)_")
    plan.append("")
    plan.append(f"#### **🛤️ 중기 (3개월, 과거 90d α 양수) — {len(medium_sorted)}건**")
    plan.append("")
    if medium_sorted:
        for k, t in medium_sorted[:8]:
            plan.append(fmt_row(k, t, "90d"))
    else:
        plan.append("_(오늘 통과 픽 없음 — 중기 진입 자제)_")
    plan.append("")
    plan.append("**현금 관리**")
    plan.append("- 위 픽들은 historical 패턴 매칭이며 미래 보장 아님")
    plan.append("- 단일 종목 비중 5~10% 상한, 전체 현금 30%+ 권장")
    plan.append("")
    return "\n".join(plan) + "\n"


def render_one_liner(themes_all: list[dict]) -> str:
    """한 줄 요약 — 단기 1위 + 중기 1위 픽 기반."""
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
        nm = short_top.get("canon") or short_top["name"][:25]
        parts.append(f"단기는 **{nm[:25]}**")
    if medium_top:
        nm = medium_top.get("canon") or medium_top["name"][:25]
        parts.append(f"중기는 **{nm[:25]}**")
    if not parts:
        return "\n> **한 줄 요약:** 오늘은 α 패턴 통과 픽이 부족 — 관망 권장.\n"
    return f"\n> **한 줄 요약:** {' · '.join(parts)} — historical α 양수 매칭만 추려 분할 진입.\n"


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

    head = (
        f"# 📊 {today.strftime('%Y.%m.%d')} Market Insight & Strategy\n\n"
        f"> 5채널 최근 {args.lookback}일 추출본 중 **historical α 양수 패턴 매칭 테마**만 표시.\n"
        f"> 필터 통과: {len(themes)} / {total} themes ({len(themes)*100//max(total,1)}%)\n\n"
        "---\n\n"
    )

    sect1 = render_market_temp(views, warnings, len(themes), total)
    sect2 = render_section(
        "2. 🔥 The Consensus (강력한 기회)",
        "여러 채널이 동시에 거론하면서, 과거 α 양수 패턴에 매칭된 테마 — 가장 신뢰도 높음.",
        grouped["consensus"], args.top_consensus,
        "_(오늘 consensus picks 없음 — 1채널 niche 또는 battleground 위주 전략)_",
    )
    sect3 = render_section(
        "3. ⚖️ The Battleground (전략적 선택)",
        "동일 테마에 대해 채널 간 stance 가 갈리는 — 진입 타이밍이 핵심인 픽.",
        grouped["battleground"], args.top_battleground,
        "_(오늘 battleground picks 없음 — 합의·niche 픽으로 진행)_",
    )
    sect4 = render_section(
        "4. 💎 Unique Alpha (틈새 전략)",
        "단일 채널 high-conviction (≥4) 픽. 단기 트레이딩 영역.",
        grouped["niche"], args.top_niche,
        "_(오늘 niche picks 없음)_",
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
