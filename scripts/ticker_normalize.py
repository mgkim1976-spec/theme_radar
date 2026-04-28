"""Normalize ticker names against KRX whitelist using fuzzy matching.

Returns normalized_name (정식 종목명) or original (해외종목·미상장).
"""
import json
import re
import sys
from pathlib import Path
from rapidfuzz import fuzz, process

sys.path.insert(0, str(Path(__file__).parent))
from config import KRX_TICKERS

WHITELIST_PATH = KRX_TICKERS

# Foreign tickers commonly mentioned by Korean YouTubers — pass through unchanged
FOREIGN_NAMES = {
    "테슬라", "엔비디아", "마이크론", "애플", "구글", "메타", "아마존",
    "마이크로소프트", "MSFT", "AAPL", "GOOG", "GOOGL", "TSLA", "NVDA",
    "AMD", "인텔", "INTC", "브로드컴", "AVGO", "퀄컴", "QCOM",
    "샌디스크", "WDC", "씨게이트", "STX", "팔란티어", "PLTR",
    "AMAT", "어플라이드머티리얼즈", "램리서치", "LRCX", "KLAC",
    "TSMC", "ASML", "ARM",
}

_db = None
def _load():
    global _db
    if _db is not None:
        return _db
    records = json.loads(WHITELIST_PATH.read_text())
    # Build alias → canonical name map
    alias_to_canon = {}
    for r in records:
        for a in r["aliases"]:
            alias_to_canon[a] = r["name"]
    _db = {
        "records": records,
        "alias_to_canon": alias_to_canon,
        "all_aliases": list(alias_to_canon.keys()),
    }
    return _db


def _clean(name: str) -> str:
    """Strip whitespace, parens, and trailing notes."""
    name = name.strip()
    # Remove parenthetical notes like "(취지)", "(언급 취지)"
    name = re.sub(r"\([^)]*취지[^)]*\)", "", name).strip()
    name = re.sub(r"\(언급[^)]*\)", "", name).strip()
    return name


def normalize(name: str, score_threshold: int = 88) -> dict:
    """Normalize a ticker name. Returns dict with status and canonical."""
    cleaned = _clean(name)
    if not cleaned:
        return {"original": name, "canonical": None, "status": "empty", "score": 0}

    # Foreign? exact match only (avoid false positives like 삼성전자→삼성)
    no_space = cleaned.replace(" ", "")
    if cleaned in FOREIGN_NAMES or no_space in FOREIGN_NAMES:
        return {"original": name, "canonical": cleaned, "status": "foreign", "score": 100}

    db = _load()
    # Exact match first
    if no_space in db["alias_to_canon"]:
        return {"original": name, "canonical": db["alias_to_canon"][no_space],
                "status": "exact", "score": 100}
    if cleaned in db["alias_to_canon"]:
        return {"original": name, "canonical": db["alias_to_canon"][cleaned],
                "status": "exact", "score": 100}

    # Fuzzy match
    match = process.extractOne(no_space, db["all_aliases"], scorer=fuzz.WRatio,
                                score_cutoff=score_threshold)
    if match:
        alias, score, _ = match
        return {"original": name, "canonical": db["alias_to_canon"][alias],
                "status": "fuzzy", "score": int(score)}

    return {"original": name, "canonical": None, "status": "unknown", "score": 0}


def normalize_extraction(extraction: dict) -> dict:
    """Apply ticker normalization to all themes/tickers in an extraction result.
    Mutates in place and adds _ticker_normalization summary.
    """
    stats = {"exact": 0, "fuzzy": 0, "foreign": 0, "unknown": 0, "empty": 0}

    # themes[].tickers
    for t in extraction.get("themes", []):
        normalized_tickers = []
        for tk in t.get("tickers", []):
            r = normalize(tk)
            stats[r["status"]] += 1
            normalized_tickers.append({
                "raw": tk,
                "name": r["canonical"] or tk,
                "status": r["status"],
                "score": r["score"],
            })
        t["tickers_normalized"] = normalized_tickers

    # tickers_mentioned
    for tk in extraction.get("tickers_mentioned", []):
        r = normalize(tk["name"])
        # Don't double-count (already counted in themes), but normalize the name
        tk["name_normalized"] = r["canonical"] or tk["name"]
        tk["normalization_status"] = r["status"]
        tk["normalization_score"] = r["score"]

    extraction["_ticker_normalization"] = stats
    return extraction


if __name__ == "__main__":
    # Self-test
    test_cases = [
        "삼성전자", "삼전", "하이닉스", "SK하이닉스",
        "두산에너빌리티", "현대일렉트릭", "현대 일렉트릭",
        "LG에너지솔루션", "LG엔솔",
        "테슬라", "마이크론",
        "보노노이", "ARp", "한전,k파트",  # 환각·노이즈
        "현대중공업", "HD현대중공업",
        "효성중공업", "엔비디아",
    ]
    for t in test_cases:
        r = normalize(t)
        print(f"  {t:25} → {r['canonical'] or '?':25} [{r['status']:7} score={r['score']}]")
