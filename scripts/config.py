"""theme_radar 공통 설정 — 모든 스크립트가 import.

v2.3부터 yaml 기반 외부화 (config/*.yaml). 다른 사용자가 채널 리스트만 다르게
가지고 있어도 코드 수정 없이 동작.

로드 순서:
  1. config/channels.yaml       채널 리스트
  2. config/project.yaml        VAULT 경로, region, integrations
  3. config/lens_presets.yaml   lens별 기본값

yaml 파일 없으면 baked-in defaults 로 fallback (backward compat).
신규 사용자는 `python3 scripts/init_project.py` 로 yaml 자동 생성.
"""
from pathlib import Path

import yaml

# ============================================================
# PROJECT ROOT (자동 감지 — 폴더 rename 시 자동 적응)
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = PROJECT_ROOT / "scripts"
DATA = PROJECT_ROOT / "data"
LOGS = PROJECT_ROOT / "logs"
SCHEDULER = PROJECT_ROOT / "scheduler"
CONFIG_DIR = PROJECT_ROOT / "config"

# YouTube 데이터
YOUTUBE_DATA = DATA / "youtube"
REFERENCE = DATA / "reference"
KRX_TICKERS = REFERENCE / "krx_tickers.json"

#   reference/         → static reference data (krx_tickers, ticker_alias, vocabularies/)
#   reference/compiled → 매일 재생성되는 artifact (theme_dictionary, scorecard, ...)
#   reference/cache    → LLM 캐시 (영구 보존 가치)
COMPILED = REFERENCE / "compiled"
CACHE = REFERENCE / "cache"
COMPILED.mkdir(parents=True, exist_ok=True)
CACHE.mkdir(parents=True, exist_ok=True)

# ============================================================
# YAML 로더 (없으면 빈 dict)
# ============================================================
def _load_yaml(name: str) -> dict:
    p = CONFIG_DIR / name
    if not p.exists():
        return {}
    try:
        return yaml.safe_load(p.read_text()) or {}
    except Exception as ex:
        print(f"[config] WARN: {name} 로드 실패 — {ex}. 기본값 사용")
        return {}

_PROJECT = _load_yaml("project.yaml")
_CHANNELS = _load_yaml("channels.yaml")
_LENS = _load_yaml("lens_presets.yaml")

# ============================================================
# Defaults (yaml 없을 때 fallback)
# 신규 사용자: `init_project.py` 가 yaml 자동 생성. 또는 config/project.example.yaml 복사.
# ============================================================
_DEFAULT_VAULT = str(PROJECT_ROOT / "vault")  # 로컬 vault 폴더 (Obsidian 연동 가능)
_DEFAULT_CATALYSTS = ""  # geopolitical_investor 통합 시 project.yaml 에서 설정
_DEFAULT_LENS_PRESETS = {
    "macro":     {"stock_weight": 0.6, "max_videos_per_run": 20},
    "top-down":  {"stock_weight": 0.8, "max_videos_per_run": 30},
    "sector":    {"stock_weight": 0.9, "max_videos_per_run": 30},
    "bottom-up": {"stock_weight": 1.2, "max_videos_per_run": 30},
}
_DEFAULT_CHANNELS = {
    "han_gyunsoo": {"name": "한균수의 주식사용설명서", "channel_id": "UCadSWH0pDXxEatvLHEHCWlg",
                    "style": "시황+종목 (단기)", "lens": "top-down", "stock_weight": 0.7},
    "86bunga": {"name": "86번가", "channel_id": "UCR6Z2_Zg3M9lpot90vpZGdw",
                "style": "매크로·밸류에이션", "lens": "macro", "stock_weight": 0.5},
    "seo_jaehyung": {"name": "서재형의 투자교실", "channel_id": "UCtmKBFeri9hx9DOaVSSvvvw",
                     "style": "산업 사이클", "lens": "top-down", "stock_weight": 1.3},
    "supergaemi": {"name": "슈퍼개미 이세무사", "channel_id": "UCowHl0BGalL433P6bCBgeKA",
                   "style": "트레이딩 + 개별주식", "lens": "bottom-up"}

}

# ============================================================
# 외부 위치 — yaml 우선, defaults fallback
# ============================================================
VAULT = Path(((_PROJECT.get("vault") or {}).get("path")) or _DEFAULT_VAULT)
CATALYSTS_YAML = Path(
    (((_PROJECT.get("integrations") or {}).get("geopolitical_investor") or {}).get("catalysts_yaml"))
    or _DEFAULT_CATALYSTS
)

REGION = (_PROJECT.get("region") or {}).get("code", "KR")
EXTRACTION_MODEL = (_PROJECT.get("extraction") or {}).get("model", "gpt-5.4-nano")

INTEGRATIONS = _PROJECT.get("integrations") or {}

# ============================================================
# Lens presets + 채널 dict
# ============================================================
LENS_PRESETS = _LENS.get("lens_presets") or _DEFAULT_LENS_PRESETS
_RAW_CHANNELS = _CHANNELS.get("channels") or _DEFAULT_CHANNELS

def _resolve(meta: dict) -> dict:
    """LENS_PRESETS 적용 — 명시값 우선, lens 기본값 fallback."""
    lens = meta.get("lens", "top-down")
    preset = LENS_PRESETS.get(lens, LENS_PRESETS.get("top-down", {}))
    out = dict(preset)
    out.update(meta)
    return out

CHANNELS = {k: _resolve(v) for k, v in _RAW_CHANNELS.items()}

def channel_paths(subdir):
    """채널별 디렉터리 경로 dict 반환."""
    base = YOUTUBE_DATA / subdir
    return {
        "base": base,
        "transcripts": base / "transcripts",
        "extractions": base / "extractions_v2",
    }

# ============================================================
# Self-test
# ============================================================
if __name__ == "__main__":
    print("=== theme_radar config (v2.3) ===")
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print(f"CONFIG_DIR:   {CONFIG_DIR}  (exists={CONFIG_DIR.exists()})")
    print(f"VAULT:        {VAULT}  (exists={VAULT.exists()})")
    print(f"REGION:       {REGION}")
    print(f"MODEL:        {EXTRACTION_MODEL}")
    print(f"CHANNELS:     {list(CHANNELS.keys())}")
    print(f"  source: {'yaml' if _CHANNELS else 'defaults'}")
    print(f"INTEGRATIONS: {list(INTEGRATIONS.keys())}")
    print(f"CATALYSTS_YAML: {CATALYSTS_YAML}")
