"""daily_alpha_digest — 과거 α 패턴이 양수인 신규 mention 만 추려 daily 리포트 생성.

용도:
  매일 아침 "투자 의사결정에 도움이 되는 한 페이지" — 채널 × 신호 × 이벤트 × 테마의
  과거 90d/30d/7d α 패턴이 양수인 조합만 추려 보여줌.

전략:
  1. alpha_lookups.json 로드 (channel×signal, event_type, canonical 별 multi-window α)
  2. 최근 N 일 (default 7) extraction 의 모든 (theme × ticker) mention 수집
  3. 각 mention 의 expected α 계산:
       - score_short = max(channel|signal 30d median, event_type 30d median, canonical 30d median)
       - score_medium = 동일하지만 90d
     (lookup 없는 경우 None — 해당 mention 은 short/medium 중 하나만 표시 가능)
  4. 단기 섹션: score_short > 0 정렬, 중기 섹션: score_medium > 0 정렬
  5. 출력: VAULT/daily_alpha.md (덮어쓰기) + VAULT/daily_alpha/{date}.md (아카이브)

사용:
  python3 daily_alpha_digest.py                 # default lookback=7 days, top=20 per section
  python3 daily_alpha_digest.py --lookback 14
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import VAULT, COMPILED, CHANNELS, channel_paths

ALPHA_LOOKUP_PATH = COMPILED / "alpha_lookups.json"
TD_PATH = COMPILED / "theme_dictionary.json"

OUT_PAGE = VAULT / "daily_alpha.md"
ARCHIVE_DIR = VAULT / "daily_alpha"


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


def collect_mentions(lookback_days: int, today: date) -> list[dict]:
    """최근 N 일의 (theme × ticker) mention 수집."""
    cutoff = today - timedelta(days=lookback_days)
    mentions = []
    for ch in CHANNELS:
        ext_dir = channel_paths(ch).get("extractions")
        if not ext_dir or not ext_dir.exists():
            continue
        for f in sorted(ext_dir.glob("*.json")):
            date_str = f.name[:8]
            try:
                d = datetime.strptime(date_str, "%Y%m%d").date()
            except ValueError:
                continue
            if d < cutoff:
                continue
            try:
                e = json.loads(f.read_text())
            except Exception:
                continue
            video_id = e.get("_meta", {}).get("video_id", "")
            title = e.get("_meta", {}).get("title", "")[:80]
            for t in e.get("themes", []):
                tn = (t.get("name") or "").strip()
                if not tn:
                    continue
                signals = t.get("discovery_signals", [])
                tickers_raw = t.get("tickers", []) or []
                tickers_norm = t.get("tickers_normalized", []) or []
                ticker_names = []
                for tk in tickers_norm:
                    nm = tk.get("name") or tk.get("raw")
                    if nm:
                        ticker_names.append(nm)
                if not ticker_names and tickers_raw:
                    ticker_names = [t for t in tickers_raw if t]
                mentions.append({
                    "channel": ch,
                    "date": date_str,
                    "theme_name": tn,
                    "stance": t.get("stance", "neutral"),
                    "conviction": int(t.get("conviction", 0) or 0),
                    "signals": signals,
                    "event_type": t.get("event_type", "미해당"),
                    "tickers": ticker_names[:4],
                    "rationale": (t.get("rationale") or "")[:200],
                    "horizon": t.get("time_horizon", ""),
                    "video_id": video_id,
                    "title": title,
                })
    return mentions


def expected_alpha(mention: dict, lookups: dict, alias_to_canon: dict, window: str) -> dict:
    """주어진 윈도우(예: '30d', '90d')에서 expected α 계산.

    return: {"alpha": float|None, "source": str, "n": int, "details": [...]}
    """
    candidates = []  # (alpha, source, n)

    ch = mention["channel"]
    by_cs = lookups.get("by_channel_signal", {})
    for sig in mention["signals"]:
        key = f"{ch}|{sig}"
        s = by_cs.get(key, {}).get(window)
        if s and s["median"] is not None:
            candidates.append((s["median"], f"ch×sig:{sig}", s["n"]))

    by_evt = lookups.get("by_event_type", {})
    s = by_evt.get(mention["event_type"], {}).get(window)
    if s and s["median"] is not None:
        candidates.append((s["median"], f"evt:{mention['event_type']}", s["n"]))

    canon = alias_to_canon.get(mention["theme_name"])
    if canon:
        s = lookups.get("by_canonical", {}).get(canon, {}).get(window)
        if s and s["median"] is not None:
            candidates.append((s["median"], f"canon:{canon}", s["n"]))

    if not candidates:
        return {"alpha": None, "source": None, "n": 0, "details": []}

    # 채택: median 의 max (best evidence)
    best = max(candidates, key=lambda c: c[0])
    return {
        "alpha": best[0],
        "source": best[1],
        "n": best[2],
        "details": candidates,
    }


def render_pick_row(m: dict, ea: dict, window_label: str) -> str:
    tickers = " · ".join(m["tickers"]) if m["tickers"] else "_(no ticker)_"
    sigs = ", ".join(m["signals"][:3])
    a_pct = f"+{ea['alpha']*100:.2f}%"
    src = ea["source"]
    n = ea["n"]
    rationale = m["rationale"][:140]
    return (
        f"### {m['theme_name'][:60]}\n"
        f"- **{tickers}** · {m['channel']} · {m['date']} · "
        f"`{m['stance']}` conv={m['conviction']} horizon={m['horizon']}\n"
        f"- exp {window_label} α: **{a_pct}** (source: `{src}`, n={n})\n"
        f"- signals: {sigs}\n"
        f"- 화자: _{rationale}_\n"
    )


def render_page(today: date, picks_short: list, picks_medium: list,
                lookback_days: int, n_total: int, n_filtered: int) -> str:
    head = (
        f"# 🎯 Daily Alpha — {today.isoformat()}\n\n"
        f"> 과거 α 패턴 (KRX→KODEX200, US→SPY index-relative) 이 **양수** 인 "
        f"채널×신호 / event_type / canonical theme 조합에 매칭된 신규 mention 만 표시.\n"
        f"> lookback {lookback_days}일 · 추출 mention {n_total} · 필터 통과 (단기 또는 중기 양수) {n_filtered}\n"
        f"> 같은 테마가 단기/중기 양쪽에 뜨면 consistent — 가장 선호되는 신호.\n\n"
        "---\n\n"
    )

    s_short = "## 🚀 단기 (30d 기준 양수) — Top 20\n\n"
    if picks_short:
        for m, ea in picks_short:
            s_short += render_pick_row(m, ea, "30d")
    else:
        s_short += "_(해당 없음)_\n"

    s_medium = "\n---\n\n## 🛤️ 중기 (90d 기준 양수) — Top 20\n\n"
    if picks_medium:
        for m, ea in picks_medium:
            s_medium += render_pick_row(m, ea, "90d")
    else:
        s_medium += "_(해당 없음)_\n"

    foot = (
        "\n---\n\n"
        "## 사용 가이드\n"
        "- **단기 (30d)**: 1개월 이내 catalyst 가 발현하는 차트·수급·실적 발표\n"
        "- **중기 (90d)**: 분기 이상 호흡, 펀더멘털·밸류에이션·구조적 변화\n"
        "- **consistent (양쪽 모두 표시)**: 단기 + 중기 모두 양수 → 가장 안정적인 picks\n"
        "- **source 의미**:\n"
        "  - `ch×sig:<신호>`: 이 채널이 이 신호로 발굴할 때 historical median α (가장 예측력 높음)\n"
        "  - `evt:<이벤트>`: corporate event_type 의 historical α\n"
        "  - `canon:<테마>`: canonical theme 의 historical α (반복 등장한 테마)\n"
        "- 매핑되지 않은 mention 은 표시되지 않음 — 새 신호/채널/테마는 데이터 누적 필요\n"
    )
    return head + s_short + s_medium + foot


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=7)
    ap.add_argument("--top", type=int, default=20)
    args = ap.parse_args()

    if not ALPHA_LOOKUP_PATH.exists():
        print(f"[daily_alpha] {ALPHA_LOOKUP_PATH} 없음 — alpha_lookups.py 먼저 실행")
        return

    lookups = json.loads(ALPHA_LOOKUP_PATH.read_text())
    alias_to_canon = load_alias_to_canon()

    today = date.today()
    mentions = collect_mentions(args.lookback, today)
    print(f"[daily_alpha] lookback={args.lookback}d → {len(mentions)} mentions")

    # 점수 계산
    scored = []
    for m in mentions:
        ea_short = expected_alpha(m, lookups, alias_to_canon, "30d")
        ea_medium = expected_alpha(m, lookups, alias_to_canon, "90d")
        scored.append((m, ea_short, ea_medium))

    # 단기 / 중기 picks (양수만, 정렬, top N)
    short_pos = [(m, ea_s) for m, ea_s, _ in scored
                 if ea_s["alpha"] is not None and ea_s["alpha"] > 0]
    medium_pos = [(m, ea_m) for m, _, ea_m in scored
                  if ea_m["alpha"] is not None and ea_m["alpha"] > 0]
    short_pos.sort(key=lambda x: -x[1]["alpha"])
    medium_pos.sort(key=lambda x: -x[1]["alpha"])

    # dedup by theme + ticker (한 영상에 여러 ticker 면 첫 ticker 만)
    def dedup(picks):
        seen = set()
        out = []
        for m, ea in picks:
            key = (m["theme_name"], tuple(m["tickers"][:1]))
            if key in seen:
                continue
            seen.add(key)
            out.append((m, ea))
            if len(out) >= args.top:
                break
        return out

    picks_short = dedup(short_pos)
    picks_medium = dedup(medium_pos)

    # 통과 ratio: 단기 또는 중기 양수
    n_filtered = sum(
        1 for _, ea_s, ea_m in scored
        if (ea_s["alpha"] or 0) > 0 or (ea_m["alpha"] or 0) > 0
    )

    page = render_page(today, picks_short, picks_medium, args.lookback, len(mentions), n_filtered)

    OUT_PAGE.parent.mkdir(parents=True, exist_ok=True)
    OUT_PAGE.write_text(page)
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (ARCHIVE_DIR / f"{today.isoformat()}.md").write_text(page)

    # 인덱스 페이지에 backlink (이미 today.md 가 있으니 daily_alpha 추가)
    print(f"[daily_alpha] short_picks={len(picks_short)}, medium_picks={len(picks_medium)}")
    print(f"  → {OUT_PAGE}")
    print(f"  archive → {ARCHIVE_DIR / (today.isoformat() + '.md')}")


if __name__ == "__main__":
    main()
