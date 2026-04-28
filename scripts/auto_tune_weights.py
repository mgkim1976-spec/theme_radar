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


# Alpha 기반 가중치 — 시기 효과 제거된 진짜 신호
# alpha = ticker_return - benchmark_return (KRX→KOSPI ETF 069500, US→SPY)
# alpha 윈도우별 임계값 (raw return보다 절댓값 작음)
WINDOW_ALPHA = {
    "30d": {"strong": 0.05, "scale": 6.0, "weak": -0.03},  # 30d alpha +5% = strong, -3% = weak
    "60d": {"strong": 0.08, "scale": 4.0, "weak": -0.05},
    "90d": {"strong": 0.10, "scale": 3.0, "weak": -0.08},
}


def select_window(entry: dict) -> tuple[str, dict] | tuple[None, None]:
    """가장 긴 윈도우 중 n_alpha ≥ MIN_OBS 인 것 우선. alpha 데이터 없으면 raw fallback."""
    for key in ("90d", "60d", "30d"):
        w = entry.get(key)
        if not w:
            continue
        n = w.get("n_alpha", w.get("n", 0))
        if n >= MIN_OBS:
            return key, w
    return None, None


def compute_weight(mean_alpha: float | None, win_rate_alpha: float | None,
                   n: int, window: str,
                   mean_raw: float | None = None, win_rate_raw: float | None = None) -> float | None:
    """alpha 기반 가중치. alpha 데이터 없으면 raw로 fallback."""
    if n < MIN_OBS or window not in WINDOW_ALPHA:
        return None

    # alpha 우선
    if mean_alpha is not None and win_rate_alpha is not None:
        bm = WINDOW_ALPHA[window]
        # bonus: 강한 alpha 보상 (capped)
        bonus = max(0.0, mean_alpha - 0.0) * bm["scale"]
        bonus = min(bonus, 0.6)
        # penalty: 음의 alpha + 낮은 win
        if mean_alpha < bm["weak"]:
            penalty = 0.40  # severe — market 대비 의미 있게 손해
        elif mean_alpha < 0:
            penalty = 0.25  # mild negative alpha
        elif win_rate_alpha < 0.45:
            penalty = 0.15  # win rate 낮음
        else:
            penalty = 0.0
        weight = 1.0 + bonus - penalty
    elif mean_raw is not None:
        # alpha 데이터 부족 시 raw로 fallback (보수적)
        weight = 0.7 + max(0.0, mean_raw) * 1.0
    else:
        return None

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

        n_alpha = w.get("n_alpha", 0)
        mean_alpha = w.get("mean_alpha")
        win_alpha = w.get("win_rate_alpha")
        n_raw = w.get("n", 0)
        mean_raw = w.get("mean")
        win_raw = w.get("win_rate")
        n_used = n_alpha if mean_alpha is not None else n_raw
        new_w = compute_weight(mean_alpha, win_alpha, n_used, window_key,
                                mean_raw, win_raw)

        if new_w is None:
            chosen = default_w
            source = f"config_default (compute_weight returned None)"
        else:
            chosen = new_w
            tag = "alpha" if mean_alpha is not None else "raw"
            source = f"auto_tuned ({window_key}, {tag})"
        # 표시용
        n = n_used
        mean = mean_alpha if mean_alpha is not None else mean_raw or 0.0
        win = win_alpha if win_alpha is not None else win_raw or 0.5

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
        "version": 2,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "rule": "weight = 1.0 + max(0, mean_alpha)*scale - penalty (alpha-based, index-relative)",
        "benchmark": "KRX→069500 (KODEX 200), US→SPY",
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
