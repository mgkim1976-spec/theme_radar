"""theme_to_stock — canonical theme × ticker 매트릭스 생성.

bottom-up 채널(예: supergaemi)에서 언급된 종목이 어떤 canonical theme에
연결되는지 가중 점수로 누적. top-down 채널은 가중치 낮음.

흐름:
  1. theme_dictionary.json 로드 (canonical_themes + aliases)
  2. 모든 추출 순회 → themes[]에서 (canonical, ticker, conviction, channel) 추출
  3. 점수: score(theme, ticker) = Σ conviction × CHANNELS[ch].stock_weight
  4. 출력: data/reference/theme_to_stock_matrix.json
       {
         "<canonical_theme>": {
           "tickers": [
             {"name": "두산에너빌리티", "krx_status": "kospi", "score": 12.4,
              "n_mentions": 8, "channels": [...], "first": "...", "last": "..."}
           ],
           "top10": [위 리스트 score 기준 top10 name]
         }
       }

LLM 미사용. 비용 0.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CHANNELS, COMPILED, channel_paths

DICT_PATH = COMPILED / "theme_dictionary.json"
MATRIX_PATH = COMPILED / "theme_to_stock_matrix.json"
WEIGHTS_PATH = COMPILED / "channel_weights.json"


def _load_auto_weights() -> dict[str, float]:
    """auto_tune_weights가 산출한 channel_weights.json (있으면).
    return: {subdir: weight}. 없으면 빈 dict (config 기본값 fallback)."""
    if not WEIGHTS_PATH.exists():
        return {}
    try:
        d = json.loads(WEIGHTS_PATH.read_text())
        return {k: v.get("weight") for k, v in d.get("channels", {}).items()
                if isinstance(v, dict) and v.get("weight") is not None}
    except Exception:
        return {}


_AUTO_WEIGHTS: dict[str, float] | None = None


def channel_weight(subdir: str) -> float:
    """auto_tune_weights 산출값 우선, 없으면 config.CHANNELS의 기본값 사용."""
    global _AUTO_WEIGHTS
    if _AUTO_WEIGHTS is None:
        _AUTO_WEIGHTS = _load_auto_weights()
    if subdir in _AUTO_WEIGHTS:
        return float(_AUTO_WEIGHTS[subdir])
    return float(CHANNELS.get(subdir, {}).get("stock_weight", 1.0))


def build_matrix(dictionary: dict) -> dict:
    """canonical theme × ticker → 누적 점수 매트릭스."""
    alias_to_canon: dict[str, str] = {}
    for canon, info in dictionary["canonical_themes"].items():
        for a in info["aliases"]:
            alias_to_canon[a] = canon

    # cells[(canon, ticker_name)] = {score, n, channels, dates, krx_status}
    cells: dict[tuple, dict] = defaultdict(lambda: {
        "score": 0.0, "n": 0, "channels": set(), "dates": [],
        "krx_status": "unknown", "ticker_score": 0,
    })

    for subdir in CHANNELS:
        ext_dir = channel_paths(subdir)["extractions"]
        if not ext_dir.exists():
            continue
        w = channel_weight(subdir)
        for f in sorted(ext_dir.glob("*_gpt-5.4-nano.json")):
            try:
                e = json.loads(f.read_text())
            except Exception:
                continue
            upload_date = f.name[:8]
            for t in e.get("themes", []):
                name = (t.get("name") or "").strip()
                canon = alias_to_canon.get(name)
                if not canon:
                    continue
                conv = t.get("conviction") or 0
                if not isinstance(conv, (int, float)):
                    conv = 0
                # tickers_normalized 우선, 없으면 tickers
                tickers_norm = t.get("tickers_normalized") or []
                if tickers_norm:
                    for tk in tickers_norm:
                        tname = (tk.get("name") or tk.get("raw") or "").strip()
                        if not tname:
                            continue
                        cell = cells[(canon, tname)]
                        cell["score"] += conv * w
                        cell["n"] += 1
                        cell["channels"].add(subdir)
                        cell["dates"].append(upload_date)
                        # KRX 매칭 정보 (가장 좋은 score 보존)
                        s = tk.get("score") or 0
                        if s > cell.get("ticker_score", 0):
                            cell["ticker_score"] = s
                            cell["krx_status"] = tk.get("status", "unknown")
                else:
                    for tname in t.get("tickers") or []:
                        tname = (tname or "").strip()
                        if not tname:
                            continue
                        cell = cells[(canon, tname)]
                        cell["score"] += conv * w
                        cell["n"] += 1
                        cell["channels"].add(subdir)
                        cell["dates"].append(upload_date)

    # 매트릭스로 변환
    matrix: dict[str, dict] = defaultdict(lambda: {"tickers": [], "top10": []})
    for (canon, tname), cell in cells.items():
        dates = sorted(cell["dates"])
        matrix[canon]["tickers"].append({
            "name": tname,
            "krx_status": cell["krx_status"],
            "score": round(cell["score"], 2),
            "n_mentions": cell["n"],
            "channels": sorted(cell["channels"]),
            "first": dates[0] if dates else None,
            "last": dates[-1] if dates else None,
        })
    for canon, data in matrix.items():
        data["tickers"].sort(key=lambda x: -x["score"])
        data["top10"] = [t["name"] for t in data["tickers"][:10]]

    return dict(matrix)


def main():
    if not DICT_PATH.exists():
        print(f"[theme_to_stock] {DICT_PATH} 없음 — theme_normalizer 먼저 실행")
        return
    d = json.loads(DICT_PATH.read_text())
    matrix = build_matrix(d)

    out = {
        "version": 1,
        "generated_from": str(DICT_PATH.name),
        "n_themes": len(matrix),
        "n_unique_tickers": len({t["name"] for tx in matrix.values() for t in tx["tickers"]}),
        "matrix": matrix,
    }
    COMPILED.mkdir(parents=True, exist_ok=True)
    MATRIX_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    n_themes_with_tickers = sum(1 for v in matrix.values() if v["tickers"])
    print(f"[theme_to_stock] {n_themes_with_tickers} themes have ≥1 ticker → {MATRIX_PATH}")
    print(f"[theme_to_stock] unique tickers across all themes: {out['n_unique_tickers']}")


if __name__ == "__main__":
    main()
