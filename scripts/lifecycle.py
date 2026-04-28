"""lifecycle — 데이터 분포 기반 동적 lifecycle 임계값 + 분류 룰.

theme_pages_gen + theme_dashboard 가 공유. 정적 7일/30일/45일 하드코딩 폐기.

전략:
  1. canonical theme들의 (today - last_mention) 분포 → percentile 기반 fading 임계
  2. (today - first_mention) 분포 → percentile 기반 emerging 임계
  3. floor (절대 최소값)으로 이상치 보호 (예: 데이터 부족이어도 emerging은 7-21일 사이)
  4. 산출물: data/reference/lifecycle_thresholds.json (캐시·디버그용)

분류 룰:
  Emerging   : days_since_first <= emerging_window
  Fading     : days_since_last  >= fading_threshold AND total_mentions >= 3
  Confirming : 7일 이동 빈도 >= confirming_min AND 채널수 >= 2 (+ active recently)
  Mature     : 활성이지만 long-running (90일 이상 + 누적 ≥ 3)
"""
import json
from datetime import date, datetime, timedelta
from pathlib import Path

from config import COMPILED

THRESHOLDS_PATH = COMPILED / "lifecycle_thresholds.json"

DEFAULTS = {
    "emerging_window": 14,        # 일
    "confirming_recent_window": 7,
    "confirming_min": 2,
    "mature_min_age": 90,
    "mature_min_total": 3,
    "fading_threshold": 30,
    "fading_min_total": 3,
}


def _percentile(sorted_values: list[int], p: float) -> int:
    """0-100. 빈 리스트면 0."""
    if not sorted_values:
        return 0
    if p <= 0:
        return sorted_values[0]
    if p >= 100:
        return sorted_values[-1]
    k = (len(sorted_values) - 1) * p / 100
    f = int(k)
    c = min(f + 1, len(sorted_values) - 1)
    return int(sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f))


def compute_thresholds(
    canon_dates: list[list[date]],
    today: date | None = None,
) -> dict:
    """canon_dates[i] = sorted dates for theme i.

    분포 기반 + floor 룰:
    - emerging_window: p20 of (days_since_first), 7-21일 floor·cap
    - fading_threshold: p70 of (days_since_last), 30-180일 floor·cap
    - mature_min_age: p50 of (days_since_first), 60-365일 floor·cap
    """
    today = today or datetime.now().date()
    if not canon_dates:
        out = dict(DEFAULTS)
        out["mode"] = "default (no data)"
        return out

    last_ages = sorted((today - d[-1]).days for d in canon_dates if d)
    first_ages = sorted((today - d[0]).days for d in canon_dates if d)

    p20_first = _percentile(first_ages, 20)
    p50_first = _percentile(first_ages, 50)
    p70_last = _percentile(last_ages, 70)

    out = dict(DEFAULTS)
    out["emerging_window"] = max(7, min(21, p20_first or 14))
    out["fading_threshold"] = max(30, min(180, p70_last or 30))
    out["mature_min_age"] = max(60, min(365, p50_first or 90))
    out["mode"] = "data-driven"
    out["computed_from"] = {
        "n_themes": len(canon_dates),
        "p20_first_age": p20_first,
        "p50_first_age": p50_first,
        "p70_last_age": p70_last,
    }
    return out


def classify(
    occ_dates: list[date],
    n_channels: int,
    thresholds: dict,
    today: date | None = None,
) -> str:
    """단일 테마의 occurrence dates → lifecycle 라벨."""
    today = today or datetime.now().date()
    if not occ_dates:
        return "Unknown"
    dates = sorted(occ_dates)
    first, last = dates[0], dates[-1]
    days_since_first = (today - first).days
    days_since_last = (today - last).days
    n_total = len(dates)

    # Fading 우선 (마지막 활동이 한참 전)
    if days_since_last >= thresholds["fading_threshold"] and n_total >= thresholds["fading_min_total"]:
        return "Fading"

    # Emerging (첫 등장이 윈도우 내)
    if days_since_first <= thresholds["emerging_window"]:
        return "Emerging"

    # Confirming (최근 7일 빈도 + ≥ 2 채널)
    cutoff = today - timedelta(days=thresholds["confirming_recent_window"])
    recent_count = sum(1 for d in dates if d >= cutoff)
    if recent_count >= thresholds["confirming_min"] and n_channels >= 2:
        return "Confirming"

    # Mature (충분히 오래되고 자주 등장)
    if days_since_first >= thresholds["mature_min_age"] and n_total >= thresholds["mature_min_total"]:
        return "Mature"

    return "Confirming" if recent_count >= 1 else "Mature"


def save_cache(thresholds: dict):
    COMPILED.mkdir(parents=True, exist_ok=True)
    out = dict(thresholds)
    out["generated_at"] = datetime.now().isoformat(timespec="seconds")
    THRESHOLDS_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))


def load_cache() -> dict:
    if THRESHOLDS_PATH.exists():
        try:
            return json.loads(THRESHOLDS_PATH.read_text())
        except Exception:
            pass
    return dict(DEFAULTS)
