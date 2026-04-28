"""forward_validator — (theme, ticker, mention_date) → 미래 N일 수익률.

흐름:
  1. 모든 채널 추출에서 (channel, video_date, theme_name, event_type, signals,
     conviction, ticker_canonical, ticker_status) 수집
  2. ticker → resolved (KRX code or US symbol) — price_fetcher의 lookup 사용
  3. data/prices/{ticker}.csv 에서 mention_date 시점 close + 미래 close
  4. forward returns: 7d / 30d / 60d / 90d (calendar days)
  5. 출력: data/reference/forward_returns.json

윈도우가 미완료(today 이전 안 도달)면 None 저장. scorecard에서 None 제외.
"""
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA, COMPILED, CHANNELS, channel_paths
from price_fetcher import load_alias_map, load_krx_lookup, resolve_ticker

PRICES_DIR = DATA / "prices"
OUT_PATH = COMPILED / "forward_returns.json"
WINDOWS = [("7d", 7), ("30d", 30), ("60d", 60), ("90d", 90)]
TODAY = date.today()


_price_cache: dict[str, pd.DataFrame] = {}


def load_prices(ticker: str) -> pd.DataFrame | None:
    if ticker in _price_cache:
        return _price_cache[ticker]
    p = PRICES_DIR / f"{ticker}.csv"
    if not p.exists():
        _price_cache[ticker] = None
        return None
    try:
        df = pd.read_csv(p, parse_dates=["Date"])
        df["date"] = df["Date"].dt.date
        df = df.sort_values("date").reset_index(drop=True)
        _price_cache[ticker] = df
        return df
    except Exception:
        _price_cache[ticker] = None
        return None


def price_at(df: pd.DataFrame, target: date, mode: str = "on_or_before") -> float | None:
    """target 일자에 해당하는 종가. 거래일 아니면 ±방향으로 가장 가까운 거래일.
    mode='on_or_before' (mention 시점), 'on_or_after' (forward target).
    """
    if df is None or len(df) == 0:
        return None
    if mode == "on_or_before":
        eligible = df[df["date"] <= target]
        if len(eligible) == 0:
            return None
        return float(eligible.iloc[-1]["Close"])
    else:
        eligible = df[df["date"] >= target]
        if len(eligible) == 0:
            return None
        return float(eligible.iloc[0]["Close"])


def parse_yyyymmdd(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except Exception:
        return None


def compute_returns(ticker: str, mention_date: date) -> dict:
    df = load_prices(ticker)
    if df is None:
        return {"_skip": "no_price_data"}
    base = price_at(df, mention_date, "on_or_before")
    if base is None or base <= 0:
        return {"_skip": "no_base_close"}
    out = {"base_close": base, "base_date": mention_date.isoformat()}
    for label, days in WINDOWS:
        target = mention_date + timedelta(days=days)
        if target > TODAY:
            out[label] = None  # 미완료
            continue
        future = price_at(df, target, "on_or_after")
        if future is None:
            out[label] = None
            continue
        out[label] = round((future - base) / base, 5)
    return out


def collect_observations() -> list[dict]:
    """추출 → flat observations.
    각 record: channel, mention_date, theme_name, event_type, conviction,
              stance, signals, ticker_raw, ticker_resolved, market.
    """
    alias = load_alias_map()
    krx = load_krx_lookup()

    rows = []
    for ch in CHANNELS:
        base = channel_paths(ch)["extractions"]
        if not base.exists():
            continue
        for f in sorted(base.glob("*_gpt-5.4-nano.json")):
            mdate = parse_yyyymmdd(f.name[:8])
            if not mdate:
                continue
            try:
                e = json.loads(f.read_text())
            except Exception:
                continue
            for t in e.get("themes", []):
                theme_name = (t.get("name") or "").strip()
                event_type = t.get("event_type", "미해당")
                conv = t.get("conviction") or 0
                stance = t.get("stance", "neutral")
                signals = t.get("discovery_signals", []) or []
                for tk in t.get("tickers_normalized", []) or []:
                    raw = (tk.get("name") or tk.get("raw") or "").strip()
                    if not raw:
                        continue
                    r = resolve_ticker(raw, alias, krx)
                    if not r:
                        continue
                    rows.append({
                        "channel": ch,
                        "mention_date": mdate.isoformat(),
                        "theme_name": theme_name,
                        "event_type": event_type,
                        "conviction": conv,
                        "stance": stance,
                        "signals": signals,
                        "ticker_raw": raw,
                        "ticker_resolved": r[0],
                        "market": r[1],
                    })
    return rows


def main():
    print(f"[forward_validator] today={TODAY}")
    obs = collect_observations()
    print(f"[forward_validator] observations: {len(obs)}")

    # ticker별 그룹핑 (price load 1회만)
    enriched: list[dict] = []
    n_priced = 0
    n_skip_noprice = 0
    n_skip_other = 0

    for r in obs:
        mdate = datetime.fromisoformat(r["mention_date"]).date()
        ret = compute_returns(r["ticker_resolved"], mdate)
        if "_skip" in ret:
            if ret["_skip"] == "no_price_data":
                n_skip_noprice += 1
            else:
                n_skip_other += 1
            continue
        n_priced += 1
        merged = {**r, "returns": ret}
        enriched.append(merged)

    print(f"[forward_validator] priced: {n_priced}")
    print(f"[forward_validator] skipped (no price data): {n_skip_noprice}")
    print(f"[forward_validator] skipped (other): {n_skip_other}")

    # 윈도우별 완료율
    for label, _ in WINDOWS:
        n_complete = sum(1 for r in enriched if r["returns"].get(label) is not None)
        print(f"  {label} 완료: {n_complete} / {n_priced}")

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": TODAY.isoformat(),
        "windows": [w for w, _ in WINDOWS],
        "n_observations": len(enriched),
        "observations": enriched,
    }
    COMPILED.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"[forward_validator] → {OUT_PATH}")


if __name__ == "__main__":
    main()
