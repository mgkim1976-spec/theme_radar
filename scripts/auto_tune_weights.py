"""auto_tune_weights — forward returns 기반 채널 stock_weight 자동 갱신.

Loop closure: forward_validator → scorecard → 이 모듈 → channel_weights.json
              ↓
              theme_to_stock.py 가 channel_weights.json 우선 사용
              (없으면 config.CHANNELS의 기본값 fallback)

규칙 (transparent + adjustable):
  - n < 30: 데이터 부족 → 기본값 유지 (None 기록)
  - bonus = max(0, mean_90d - 0.10) × 2.0 (10% market beta 위 excess), cap 0.6
  - penalty = mean_90d < 0.05 → 0.30, OR win_rate < 0.50 → 0.20, else 0
  - weight = 1.0 + bonus - penalty
  - clamp [0.3, 2.0]

매주 forward_returns 갱신 시 자동 재계산. 변화는 delta 로그에 기록.
"""
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import COMPILED, CHANNELS

SCORECARD_PATH = COMPILED / "scorecard.json"
WEIGHTS_PATH = COMPILED / "channel_weights.json"
MIN_OBS = 30  # 가중치 산출에 필요한 최소 관측 수


# 윈도우별 thresholds (대략 1/3, 2/3, 1 비례)
WINDOW_BENCHMARK = {
    "30d": {"market": 0.04, "scale": 5.0, "weak": 0.04},
    "60d": {"market": 0.07, "scale": 3.5, "weak": 0.05},
    "90d": {"market": 0.10, "scale": 2.0, "weak": 0.05},
}


def select_window(entry: dict) -> tuple[str, dict] | tuple[None, None]:
    """가장 긴 (가장 높은 신호) 윈도우 중 n ≥ MIN_OBS 인 것 선택."""
    for key in ("90d", "60d", "30d"):
        w = entry.get(key)
        if w and w.get("n", 0) >= MIN_OBS:
            return key, w
    return None, None


def compute_weight(mean: float, win_rate: float, n: int, window: str) -> float | None:
    """rule-based 가중치 산출. 윈도우별 thresholds 반영."""
    if n < MIN_OBS or window not in WINDOW_BENCHMARK:
        return None
    bm = WINDOW_BENCHMARK[window]
    bonus = max(0.0, mean - bm["market"]) * bm["scale"]
    bonus = min(bonus, 0.6)
    if mean < bm["weak"]:
        penalty = 0.30
    elif win_rate < 0.50:
        penalty = 0.20
    else:
        penalty = 0.0
    weight = 1.0 + bonus - penalty
    return round(max(0.3, min(2.0, weight)), 2)


def main():
    if not SCORECARD_PATH.exists():
        print(f"[auto_tune_weights] {SCORECARD_PATH} 없음 — scorecard 먼저 실행")
        return

    sc = json.loads(SCORECARD_PATH.read_text())
    by_channel = sc.get("by_channel") or {}

    # 기존 weights 로드 (delta 계산용)
    prev: dict[str, dict] = {}
    if WEIGHTS_PATH.exists():
        try:
            old = json.loads(WEIGHTS_PATH.read_text())
            prev = old.get("channels", {})
        except Exception:
            pass

    out_channels: dict[str, dict] = {}
    for subdir in CHANNELS.keys():
        default_w = CHANNELS[subdir].get("stock_weight", 1.0)
        entry = by_channel.get(subdir)
        if not entry:
            out_channels[subdir] = {
                "weight": default_w,
                "source": "config_default (no scorecard data)",
                "computed_at": datetime.now().isoformat(timespec="seconds"),
            }
            continue
        window_key, w = select_window(entry)
        if not w:
            out_channels[subdir] = {
                "weight": default_w,
                "source": "config_default (no window with n ≥ MIN_OBS)",
                "computed_at": datetime.now().isoformat(timespec="seconds"),
            }
            continue

        n = w.get("n", 0)
        mean = w.get("mean", 0.0)
        win = w.get("win_rate", 0.5)
        new_w = compute_weight(mean, win, n, window_key)

        if new_w is None:
            chosen = default_w
            source = f"config_default (compute_weight returned None)"
        else:
            chosen = new_w
            source = f"auto_tuned ({window_key})"

        prev_w = prev.get(subdir, {}).get("weight", default_w)
        delta = round(chosen - prev_w, 2)

        out_channels[subdir] = {
            "weight": chosen,
            "previous_weight": prev_w,
            "delta": delta,
            "config_default": default_w,
            "source": source,
            "window_used": window_key,
            "n_observations": n,
            "mean_return": round(mean, 4),
            "win_rate": round(win, 3),
            "computed_at": datetime.now().isoformat(timespec="seconds"),
        }

    payload = {
        "version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rule": "weight = 1.0 + max(0, mean_90d - 0.10)*2 - penalty; clamp [0.3, 2.0]",
        "min_observations": MIN_OBS,
        "channels": out_channels,
    }
    COMPILED.mkdir(parents=True, exist_ok=True)
    WEIGHTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # 콘솔 요약
    print(f"[auto_tune_weights] → {WEIGHTS_PATH}")
    print(f"\n{'channel':<15} {'weight':>7} {'prev':>6} {'delta':>7} {'win':>5} {'mean':>7} {'n':>5}  source")
    print("-" * 95)
    for subdir, info in out_channels.items():
        delta_str = f"{info.get('delta', 0):+.2f}" if info.get("delta") not in (None, "—") else "—"
        mean_str = f"{info.get('mean_return', 0)*100:+.1f}%" if "mean_return" in info else "—"
        win_str = f"{info.get('win_rate', 0):.2f}" if "win_rate" in info else "—"
        n_str = info.get("n_observations", "—")
        print(f"{subdir:<15} {info['weight']:>7.2f} "
              f"{info.get('previous_weight', '—'):>6} "
              f"{delta_str:>7} {win_str:>5} {mean_str:>7} "
              f"{n_str:>5}  {info['source']}")


if __name__ == "__main__":
    main()
