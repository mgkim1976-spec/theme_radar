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

# 비-actionable: 시장 지수만 있고 개별 종목이 없는 픽은 Action Plan 에서 제외
INDEX_TICKERS = {"코스피", "코스닥", "S&P500", "S&P", "나스닥", "NASDAQ", "다우", "닛케이", "VIX"}

# theme dedup: 같은 어두로 시작하는 canonical 은 root 로 묶음
ROOT_GROUPS = ["반도체", "전력", "AI 데이터센터", "AI 인프라", "바이오", "원전", "조선", "방산", "로봇"]

# 픽 후보에서 제외할 educational/meta theme 키워드 (canonical 에 포함 시 제외)
PICK_STOP_KEYWORDS = ["오해", "금지", "프레임", "원칙", "기초", "장세", "조정", "변동성", "방어"]


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


def llm_synthesize(today: date, consensus: list, niche: list, warnings: list) -> dict:
    """LLM 으로 분석가 voice prose 합성. 실패 시 None 반환 (호출자가 fallback)."""
    try:
        from llm_client import chat_json
    except Exception:
        return None
    import os
    if "OPENAI_API_KEY" not in os.environ:
        return None

    KOR_DOW = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금", 5: "토", 6: "일"}
    dow = KOR_DOW.get(today.weekday(), "")

    def pack(items: list[tuple]) -> list[dict]:
        out = []
        for key, all_items in items[:6]:
            tickers = []
            seen = set()
            rationales = []
            for it in all_items:
                for tk in it["tickers"]:
                    if tk not in seen:
                        seen.add(tk)
                        tickers.append(tk)
                if it.get("rationale"):
                    rationales.append(it["rationale"][:180])
            out.append({
                "theme": pretty_name(key),
                "tickers": tickers[:6],
                "raw_evidence": " | ".join(rationales[:2])[:400],
            })
        return out

    payload = {
        "publish_date": f"{today.isoformat()} ({dow})",
        "consensus_themes": pack(consensus),
        "niche_themes": pack(niche),
        "warnings": [w[1] for w in warnings[:3]],
    }

    system = (
        "당신은 한국 retail 투자자 대상 일일 마켓 뉴스레터의 시니어 에디터입니다. "
        "주어진 데이터로 분석가 자체 voice 의 commentary 를 작성합니다.\n\n"
        "엄격한 작성 규칙:\n"
        "1. '~라고 봄', '~이라고 연결', '~한다는 관점', '~라고 한다' 같은 reportive 어미 절대 금지. "
        "분석가 자신이 단정하는 voice 로 끝맺는다 ('~다', '~된다', '~할 시점', '~을 본다').\n"
        "2. 영상 인용·출처 어휘 금지 ('영상에서', '~가 말함', '~라고 봄').\n"
        "3. 영문 메타 표현 금지 ('today is', 'this week', 'note that' 등 영문 표현 절대 사용 금지). "
        "결과는 100% 자연스러운 한국어 commentary 만.\n"
        "4. raw_evidence 는 참고 데이터일 뿐 그대로 인용 금지. 핵심 인사이트만 분석가 톤으로 재구성.\n"
        "5. 각 take 는 1~2 문장 (60~140자). 군더더기 금지.\n\n"
        "JSON 응답 키:\n"
        "  - 'headline': Section 1 한 단락 (2~3 문장, 이번 주 흐름의 구조 + 핵심 축. 도입어 없이 바로 시작)\n"
        "  - 'risk_summary': 단기 리스크 한 문장\n"
        "  - 'consensus_takes': {theme_name: take}\n"
        "  - 'niche_takes': {theme_name: take}\n"
        "  - 'one_liner': 마무리 한 문장 (단기 + 중기 강조 픽 콜아웃)\n"
    )
    user = json.dumps(payload, ensure_ascii=False)

    try:
        data, result = chat_json(system, user, model="gpt-5.4-mini")
        cost_str = f"${result.cost_usd:.4f}" if hasattr(result, "cost_usd") else "?"
        print(f"[daily_retail_alpha] LLM cost: {cost_str} ({result.input_tokens}+{result.output_tokens} tok)")
        return data
    except Exception as e:
        print(f"[daily_retail_alpha] LLM 합성 실패 — fallback: {e}")
        return None


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


def find_root(canon_pretty: str) -> str:
    """canonical 의 root 그룹 찾기 — 같은 root 는 dedup 대상."""
    for root in ROOT_GROUPS:
        if canon_pretty.startswith(root):
            return root
    return canon_pretty


def has_actionable_ticker(tickers: list[str]) -> bool:
    """개별 종목이 1개라도 있는지 (지수만 있으면 false)."""
    return any(t for t in tickers if t and t not in INDEX_TICKERS)


def is_meta_theme(canon_pretty: str) -> bool:
    """educational/meta theme 인지 — 픽 후보에서 제외."""
    return any(kw in canon_pretty for kw in PICK_STOP_KEYWORDS)


def dedup_picks_by_root(picks: list[tuple]) -> list[tuple]:
    """[(key, theme), ...] 에서 같은 root 는 가장 좋은 α 만 남기고 ticker 합집합."""
    by_root: dict[str, dict] = {}
    for key, t in picks:
        root = find_root(pretty_name(key))
        cur = by_root.get(root)
        if not cur:
            by_root[root] = {"key": key, "theme": t, "tickers": list(t["tickers"])}
        else:
            # 더 높은 α 면 교체, 종목은 합치기
            if t.get("alpha_30d", 0) > cur["theme"].get("alpha_30d", 0) or \
               t.get("alpha_90d", 0) > cur["theme"].get("alpha_90d", 0):
                cur["key"] = key
                cur["theme"] = t
            for tk in t["tickers"]:
                if tk not in cur["tickers"]:
                    cur["tickers"].append(tk)
    out = []
    for root, info in by_root.items():
        info["theme"] = dict(info["theme"])
        info["theme"]["tickers"] = info["tickers"][:6]
        out.append((root, info["theme"]))
    return out


def render_theme_block_llm(name: str, items: list[dict], take: str | None) -> str:
    """LLM take 가 있으면 그걸로, 없으면 fallback."""
    all_tickers = []
    seen = set()
    for it in items:
        for tk in it["tickers"]:
            if tk not in seen:
                seen.add(tk)
                all_tickers.append(tk)
    tk_str = ", ".join(all_tickers[:6]) if all_tickers else None

    lines = [f"#### **{pretty_name(name)[:60]}**", ""]
    if take:
        lines.append(take.strip())
    else:
        # fallback to old rendering
        return render_theme_block(name, items)
    if tk_str:
        lines.append("")
        lines.append(f"> **관련 종목:** {tk_str}")
    return "\n".join(lines) + "\n"


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


def render_market_temp_llm(headline: str, risk_summary: str | None, warnings: list, themes_all: list[dict]) -> str:
    """LLM 합성 결과 기반 Section 1."""
    txt = ["### **1. 🌡️ 시장 온도 (Market Sentiment)**", "", headline]
    if risk_summary:
        txt.append("")
        txt.append(f"> {risk_summary}")
    if warnings:
        txt.append("")
        txt.append("**이번 주 주의할 리스크**")
        for _, w in warnings[:3]:
            txt.append(f"  - {neutralize_dates(w)}")
    return "\n".join(txt) + "\n\n---\n"


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


def render_section(title: str, sub: str, groups: list[tuple], top_n: int, empty_msg: str,
                   takes: dict | None = None) -> str:
    out = [f"### **{title}**", "", f"_{sub}_", ""]
    if not groups:
        out.append(empty_msg)
        return "\n".join(out) + "\n\n---\n"
    for key, items in groups[:top_n]:
        take = (takes or {}).get(pretty_name(key)) if takes else None
        out.append(render_theme_block_llm(key, items, take))
    return "\n".join(out) + "\n---\n"


def render_action_plan(themes_all: list[dict], today: date) -> str:
    """5. Action Plan — 단기/중기 분리, dedup + 비-actionable 제외."""
    short = {}
    medium = {}
    for t in themes_all:
        key = t.get("canon") or t["name"][:40]
        # 비-actionable (지수만, 종목 없음) 제외
        if not has_actionable_ticker(t.get("tickers", [])):
            continue
        # educational/meta theme 제외
        if is_meta_theme(pretty_name(key)):
            continue
        if (t.get("alpha_30d") or 0) > 0:
            cur = short.get(key)
            if not cur or (t["alpha_30d"] > cur["alpha_30d"]):
                short[key] = t
        if (t.get("alpha_90d") or 0) > 0:
            cur = medium.get(key)
            if not cur or (t["alpha_90d"] > cur["alpha_90d"]):
                medium[key] = t

    # root 별 dedup — 반도체/반도체_AI/반도체_수급 → '반도체' 1 줄로 통합
    short_dedup = dedup_picks_by_root(list(short.items()))
    medium_dedup = dedup_picks_by_root(list(medium.items()))
    short_sorted = sorted(short_dedup, key=lambda kv: -(kv[1]["alpha_30d"] or 0))
    medium_sorted = sorted(medium_dedup, key=lambda kv: -(kv[1]["alpha_90d"] or 0))

    def fmt_row(key: str, t: dict, window: str) -> str:
        a = t[f"alpha_{window}"] * 100
        tk = ", ".join(t["tickers"][:4]) if t["tickers"] else "_(개별 종목 미언급)_"
        return f"- **{pretty_name(key)[:30]}** _(과거 평균 +{a:.1f}%)_ — {tk}"

    plan = [
        "### **5. 📌 최종 행동 지침 (Action Plan)**",
        "",
        "**🚀 단기 매수 후보 (1주~1개월)**",
        "",
    ]
    if short_sorted:
        for k, t in short_sorted[:6]:
            plan.append(fmt_row(k, t, "30d"))
    else:
        plan.append("_(오늘은 단기 후보가 부족 — 관망 권장)_")
    plan.append("")
    plan.append("**🛤️ 중기 코어 후보 (3개월)**")
    plan.append("")
    if medium_sorted:
        for k, t in medium_sorted[:6]:
            plan.append(fmt_row(k, t, "90d"))
    else:
        plan.append("_(오늘은 중기 후보가 부족 — 관망 권장)_")
    plan.append("")
    plan.append("**💰 포지션 관리**")
    plan.append("- 단일 종목 5~10% 이내, 변동성 구간엔 현금 30% 이상")
    plan.append("- 과거 패턴 기반 참고 자료이며 미래 수익을 보장하지 않습니다")
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

    # LLM 합성 (분석가 voice) — 실패 시 raw rationale fallback
    synth = llm_synthesize(today, grouped["consensus"], grouped["niche"], warnings)
    if synth:
        sect1 = render_market_temp_llm(
            synth.get("headline", ""),
            synth.get("risk_summary"),
            warnings, themes,
        )
        consensus_takes = synth.get("consensus_takes", {}) or {}
        niche_takes = synth.get("niche_takes", {}) or {}
        one_liner_text = synth.get("one_liner", "")
    else:
        sect1 = render_market_temp(views, warnings, themes, today)
        consensus_takes, niche_takes, one_liner_text = {}, {}, ""

    KOR_DOW = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금", 5: "토", 6: "일"}
    dow = KOR_DOW.get(today.weekday(), "")
    head = f"# 📊 {today.strftime('%Y.%m.%d')} ({dow}) Market Insight & Strategy\n\n"
    if one_liner_text:
        head += f"> **{one_liner_text}**\n\n"
    head += "---\n\n"

    sect2 = render_section(
        "2. 🔥 The Consensus (강력한 기회)",
        "여러 시각이 한 방향으로 모이는 핵심 섹터입니다.",
        grouped["consensus"], args.top_consensus,
        "_(오늘은 합의된 핵심 섹터가 뚜렷하지 않습니다 — 개별 테마 위주로 접근)_",
        takes=consensus_takes,
    )
    # battleground 비면 섹션 자체 생략
    if grouped["battleground"]:
        sect3 = render_section(
            "3. ⚖️ The Battleground (전략적 선택)",
            "투자 성향에 따라 진입 타이밍을 달리해야 할 승부처입니다.",
            grouped["battleground"], args.top_battleground,
            "",
        )
    else:
        sect3 = ""
    sect4 = render_section(
        "4. 💎 Unique Alpha (틈새 전략)",
        "지수와 별개로 움직이는 개별 재료·정책 모멘텀 픽입니다.",
        grouped["niche"], args.top_niche,
        "_(오늘은 두드러지는 틈새 픽이 없습니다)_",
        takes=niche_takes,
    )
    sect5 = render_action_plan(themes, today)
    # 한 줄 요약은 헤더에 이미 들어갔으므로 본문 끝에서는 생략 (중복 회피)
    one = ""

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
