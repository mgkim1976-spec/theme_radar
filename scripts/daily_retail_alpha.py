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
    """한 canonical theme 의 모든 mentions 를 한 블록으로."""
    # 가장 좋은 30d/90d 기록 추출
    best30 = max(items, key=lambda x: x.get("alpha_30d") or -99)
    best90 = max(items, key=lambda x: x.get("alpha_90d") or -99)
    a30 = best30.get("alpha_30d")
    a90 = best90.get("alpha_90d")

    # 종목 합치기
    all_tickers = []
    seen = set()
    for it in items:
        for tk in it["tickers"]:
            if tk not in seen:
                seen.add(tk)
                all_tickers.append(tk)
    tk_str = " · ".join(all_tickers[:6]) if all_tickers else "_(no ticker)_"

    chs = " / ".join(sorted({it["channel"] for it in items}))
    stances = sorted({it["stance"] for it in items})
    convs = [it["conviction"] for it in items]
    conv_max = max(convs) if convs else 0

    # 채널별 rationale snippet (처음 2개)
    rationale_lines = []
    for it in items[:2]:
        r = it["rationale"][:130]
        if r:
            rationale_lines.append(f"  - _{it['channel']}_ ({it['date']}, conv={it['conviction']}): {r}")

    a_str = []
    if a30 and a30 > 0: a_str.append(f"30d {fmt_pct(a30)} ({best30['src_30d']}, n={best30['n_30d']})")
    if a90 and a90 > 0: a_str.append(f"90d {fmt_pct(a90)} ({best90['src_90d']}, n={best90['n_90d']})")
    consistent_tag = " · ✅ **consistent**" if a30 and a90 and a30 > 0 and a90 > 0 else ""

    lines = [
        f"#### **{name[:60]}**",
        f"- **종목**: {tk_str}",
        f"- **채널**: {chs} · stance: {', '.join(stances)} · max conv: {conv_max}",
        f"- **historical α**: {' / '.join(a_str)}{consistent_tag}",
    ]
    if rationale_lines:
        lines.append("- **화자 논리**:")
        lines.extend(rationale_lines)
    return "\n".join(lines) + "\n"


def render_market_temp(views: dict, warnings: list, n_themes_passed: int, n_themes_total: int) -> str:
    """1. 시장 온도 — 채널 view 합성."""
    bullets = []
    for ch in ("han_gyunsoo", "seo_jaehyung", "supergaemi", "blueoak", "86bunga"):
        if ch in views and views[ch]:
            v = views[ch][-1]  # 가장 최근
            bullets.append(f"  - **{ch}**: {v[:200]}")
    risks = warnings[:3]

    txt = [
        "### **1. 🌡️ 시장 온도 (Market Sentiment)**",
        "",
        f"> 최근 추출된 테마 {n_themes_total}개 중 **과거 α 양수 패턴에 매칭된 {n_themes_passed}개**만 후속 섹션에 표시됩니다.",
        "",
        "**채널별 최근 시황 요약**",
    ]
    txt.extend(bullets)
    if risks:
        txt.append("")
        txt.append("**시장 경고 (warnings 발췌)**")
        for ch, w in risks:
            txt.append(f"  - _{ch}_: {w}")
    return "\n".join(txt) + "\n\n---\n"


def render_section(title: str, sub: str, groups: list[tuple], top_n: int, empty_msg: str) -> str:
    out = [f"### **{title}**", "", f"_{sub}_", ""]
    if not groups:
        out.append(empty_msg)
        return "\n".join(out) + "\n\n---\n"
    for key, items in groups[:top_n]:
        out.append(render_theme_block(key, items))
    return "\n".join(out) + "\n---\n"


def render_action_plan(grouped: dict, today: date) -> str:
    consensus = grouped["consensus"][:3]
    niche = grouped["niche"][:3]
    has_consistent = lambda items: any(it.get("alpha_30d") and it.get("alpha_90d") for it in items)
    consistent_consensus = [(k, v) for k, v in consensus if has_consistent(v)]

    plan = [
        "### **5. 📌 최종 행동 지침 (Action Plan)**",
        "",
        f"**오늘 {today.isoformat()} 기준** — 위에 나열된 픽들은 모두 historical α 양수 통과 항목입니다.",
        "",
    ]

    # 단기 트레이딩
    plan.append("**1. 단기 트레이딩 (1주~1개월)**")
    if niche:
        ts = []
        for k, items in niche[:3]:
            top_tk = next((t for it in items for t in it["tickers"]), None)
            ts.append(f"`{k[:25]}`" + (f" ({top_tk})" if top_tk else ""))
        plan.append(f"- 단일 채널 high-conviction 픽: {', '.join(ts)}")
    plan.append("- 30d α 가 큰 항목 우선 — 시초가 분할 진입, 7일 내 부분 익절")
    plan.append("")

    # 스윙
    plan.append("**2. 스윙 (1~3개월)**")
    if consensus:
        ts = []
        for k, items in consensus[:3]:
            top_tk = next((t for it in items for t in it["tickers"]), None)
            ts.append(f"`{k[:25]}`" + (f" ({top_tk})" if top_tk else ""))
        plan.append(f"- 채널 간 합의된 consensus 픽: {', '.join(ts)}")
    plan.append("- 지수 조정 시 분할 매수")
    plan.append("")

    # 장기 코어
    plan.append("**3. 장기 코어 (3개월+)**")
    if consistent_consensus:
        ts = []
        for k, items in consistent_consensus[:3]:
            top_tk = next((t for it in items for t in it["tickers"]), None)
            ts.append(f"`{k[:25]}`" + (f" ({top_tk})" if top_tk else ""))
        plan.append(f"- ✅ consistent (30d & 90d 모두 양수): {', '.join(ts)}")
    plan.append("- 30d·90d 양쪽 모두 historical α 양수 — 시간 분산 매수")
    plan.append("")

    plan.append("**4. 현금 관리**")
    plan.append("- 위 픽들은 historical 패턴 매칭일 뿐, 미래 보장 아님")
    plan.append("- 단일 종목 비중 5~10% 상한, 전체 현금 비중 30%+ 권장")

    return "\n".join(plan) + "\n"


def render_one_liner(grouped: dict) -> str:
    cons = grouped["consensus"][:1]
    nich = grouped["niche"][:1]
    parts = []
    if nich:
        parts.append(f"단기는 **{nich[0][0][:30]}**")
    if cons:
        parts.append(f"중장기는 **{cons[0][0][:30]}**")
    if not parts:
        return "\n> **한 줄 요약:** 오늘은 α 패턴 통과 픽이 부족 — 관망 권장.\n"
    return f"\n> **한 줄 요약:** {' · '.join(parts)} — historical α 양수 매칭 픽으로 분할 진입.\n"


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
    sect5 = render_action_plan(grouped, today)
    one = render_one_liner(grouped)

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
