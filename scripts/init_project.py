"""init_project — 신규 사용자가 채널 리스트만으로 theme_radar 부트스트랩.

사용:
  # 인터랙티브 (채널 1개씩 입력)
  python3 scripts/init_project.py

  # 채널 리스트 파일에서 일괄 (가장 흔한 사용)
  python3 scripts/init_project.py --channels=my_channels.txt

  # 인자로 직접
  python3 scripts/init_project.py --add UC22자ID:subdir:lens "채널명"

  # project.yaml만 (vault 경로·region 변경)
  python3 scripts/init_project.py --vault=/path/to/vault --region=US

채널 리스트 파일 형식 (whitespace separated, # 주석 허용):
  # channel_id            subdir         lens       name
  UCadSWH0pDXxEatvLHEHCWlg  han_gyunsoo  top-down   한균수의 주식사용설명서
  UCR6Z2_Zg3M9lpot90vpZGdw  86bunga      macro      86번가

lens 값: macro / top-down / sector / bottom-up

이 스크립트가 하는 일:
  1. config/ 디렉터리 생성
  2. config/project.yaml 생성 (없을 때만, 또는 인자로 변경 시)
  3. config/channels.yaml 생성/병합
  4. config/lens_presets.yaml 기본값 생성 (없을 때만)
  5. 데이터 디렉터리 생성 (data/youtube/{subdir}/transcripts·extractions_v2)
  6. KR region이면 build_krx_whitelist 실행 안내 (수동)
  7. 다음 단계 가이드 출력
"""
import argparse
import re
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"

CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
SUBDIR_RE = re.compile(r"^[a-z][a-z0-9_]*$")
VALID_LENS = {"macro", "top-down", "sector", "bottom-up"}


# ============================================================
# Defaults — yaml 파일 없을 때 이 내용으로 생성
# ============================================================
DEFAULT_PROJECT_YAML = """\
# theme_radar 프로젝트 환경 설정. init_project.py가 자동 생성.

vault:
  # Obsidian Vault 경로. 로컬: "./vault" 또는 절대 경로.
  path: "{vault_path}"

region:
  # 채널 데이터의 주요 시장. "KR" / "US" / "JP" / "OTHER"
  code: {region}

extraction:
  model: gpt-5.4-nano

integrations:
  geopolitical_investor:
    enabled: false
    catalysts_yaml: ""

  vocabulary_snapshots:
    enabled: false
    sources:
      macro_event: ""
      corporate_event: ""
"""

DEFAULT_LENS_YAML = """\
# Lens presets — 채널 추가 시 lens 만 지정하면 stock_weight·max_videos_per_run 자동 적용.
# 실제 stock_weight는 auto_tune_weights가 forward returns 기반으로 동적 갱신.

lens_presets:
  macro:
    stock_weight: 0.6
    max_videos_per_run: 20
  top-down:
    stock_weight: 0.8
    max_videos_per_run: 30
  sector:
    stock_weight: 0.9
    max_videos_per_run: 30
  bottom-up:
    stock_weight: 1.2
    max_videos_per_run: 30
"""


def parse_channel_line(line: str) -> dict | None:
    """whitespace-separated 한 줄 → dict 또는 None.
    형식: channel_id subdir lens [name...]"""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    parts = line.split(None, 3)
    if len(parts) < 3:
        return None
    cid, subdir, lens = parts[0], parts[1], parts[2]
    name = parts[3] if len(parts) >= 4 else subdir
    return {
        "subdir": subdir,
        "channel_id": cid,
        "lens": lens,
        "name": name,
    }


def validate_entry(e: dict) -> str | None:
    """검증. error 메시지 또는 None."""
    if not CHANNEL_ID_RE.match(e["channel_id"]):
        return f"channel_id 형식 오류: {e['channel_id']!r}"
    if not SUBDIR_RE.match(e["subdir"]):
        return f"subdir 형식 오류 (소문자/숫자/언더스코어): {e['subdir']!r}"
    if e["lens"] not in VALID_LENS:
        return f"lens 형식 오류: {e['lens']!r} (허용: {sorted(VALID_LENS)})"
    return None


def load_existing_channels() -> dict:
    p = CONFIG_DIR / "channels.yaml"
    if not p.exists():
        return {}
    try:
        d = yaml.safe_load(p.read_text()) or {}
    except Exception:
        return {}
    return d.get("channels") or {}


def write_channels_yaml(channels: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    p = CONFIG_DIR / "channels.yaml"
    header = """\
# theme_radar 추적 채널 — 단일 진실 원천
# 신규 채널 추가:
#   python3 scripts/add_channel.py <channel_id> <subdir> <lens> "<채널명>" --apply
#   또는 init_project.py --channels=...

"""
    body = yaml.safe_dump(
        {"channels": channels}, allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    p.write_text(header + body)


def ensure_project_yaml(vault_path: str | None, region: str | None):
    p = CONFIG_DIR / "project.yaml"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # 기존 있으면 read·merge·rewrite
    if p.exists():
        try:
            d = yaml.safe_load(p.read_text()) or {}
        except Exception:
            d = {}
        d.setdefault("vault", {})
        d.setdefault("region", {})
        d.setdefault("extraction", {})
        d.setdefault("integrations", {})
        if vault_path:
            d["vault"]["path"] = vault_path
        if region:
            d["region"]["code"] = region
        if not d["extraction"].get("model"):
            d["extraction"]["model"] = "gpt-5.4-nano"
        p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False))
        return "updated"

    # 신규
    content = DEFAULT_PROJECT_YAML.format(
        vault_path=vault_path or str(PROJECT_ROOT / "vault"),
        region=region or "KR",
    )
    p.write_text(content)
    return "created"


def ensure_lens_yaml():
    p = CONFIG_DIR / "lens_presets.yaml"
    if p.exists():
        return "kept"
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(DEFAULT_LENS_YAML)
    return "created"


def ensure_data_dirs(channels: dict):
    for subdir in channels.keys():
        base = DATA_DIR / "youtube" / subdir
        (base / "transcripts").mkdir(parents=True, exist_ok=True)
        (base / "extractions_v2").mkdir(parents=True, exist_ok=True)


def to_yaml_entry(e: dict) -> dict:
    """parse_channel_line 결과 → channels.yaml 의 단일 entry."""
    return {
        "name": e["name"],
        "channel_id": e["channel_id"],
        "lens": e["lens"],
    }


def cmd_load_channels_file(path: str) -> list[dict]:
    p = Path(path)
    if not p.exists():
        print(f"❌ 채널 리스트 파일 없음: {path}", file=sys.stderr)
        sys.exit(1)
    rows = []
    for ln in p.read_text().splitlines():
        e = parse_channel_line(ln)
        if e is None:
            continue
        err = validate_entry(e)
        if err:
            print(f"❌ {ln!r} — {err}", file=sys.stderr)
            sys.exit(1)
        rows.append(e)
    return rows


def cmd_interactive() -> list[dict]:
    print("=== 인터랙티브 채널 추가 ===  (빈 줄 입력 시 종료)")
    rows = []
    while True:
        line = input("channel_id subdir lens [name]: ").strip()
        if not line:
            break
        e = parse_channel_line(line)
        if e is None:
            print("  ⚠️ 형식 잘못됨")
            continue
        err = validate_entry(e)
        if err:
            print(f"  ⚠️ {err}")
            continue
        rows.append(e)
        print(f"  ✓ {e['subdir']} 추가됨")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--channels", help="채널 리스트 파일")
    ap.add_argument("--add", help="단일 채널: channel_id:subdir:lens")
    ap.add_argument("--name", default=None, help="--add 와 함께 사용할 채널명")
    ap.add_argument("--vault", help="VAULT 경로 (project.yaml 갱신)")
    ap.add_argument("--region", help="region 코드 (KR/US/JP/OTHER)")
    ap.add_argument("--no-data-dirs", action="store_true", help="데이터 디렉터리 생성 안 함")
    args = ap.parse_args()

    print(f"=== theme_radar init_project ===")
    print(f"PROJECT_ROOT: {PROJECT_ROOT}\n")

    # 1. project.yaml 처리
    proj_status = ensure_project_yaml(args.vault, args.region)
    print(f"  ✓ config/project.yaml: {proj_status}")
    if args.vault:
        print(f"      vault.path = {args.vault}")
    if args.region:
        print(f"      region.code = {args.region}")

    # 2. lens_presets.yaml
    lens_status = ensure_lens_yaml()
    print(f"  ✓ config/lens_presets.yaml: {lens_status}")

    # 3. 채널 수집
    new_entries: list[dict] = []
    if args.channels:
        new_entries = cmd_load_channels_file(args.channels)
        print(f"  ✓ {len(new_entries)} 채널 로드 (파일: {args.channels})")
    elif args.add:
        parts = args.add.split(":", 2)
        if len(parts) != 3:
            print("❌ --add 형식: channel_id:subdir:lens", file=sys.stderr)
            sys.exit(1)
        e = {"channel_id": parts[0], "subdir": parts[1], "lens": parts[2],
             "name": args.name or parts[1]}
        err = validate_entry(e)
        if err:
            print(f"❌ {err}", file=sys.stderr)
            sys.exit(1)
        new_entries = [e]
    elif sys.stdin.isatty():
        new_entries = cmd_interactive()

    if new_entries:
        # 기존 + 신규 병합
        existing = load_existing_channels()
        merged = dict(existing)
        n_added = n_updated = 0
        for e in new_entries:
            entry = to_yaml_entry(e)
            if e["subdir"] in merged:
                merged[e["subdir"]] = {**merged[e["subdir"]], **entry}
                n_updated += 1
            else:
                merged[e["subdir"]] = entry
                n_added += 1
        write_channels_yaml(merged)
        print(f"  ✓ config/channels.yaml: +{n_added} 추가 / {n_updated} 갱신 / {len(merged)} 총")

        if not args.no_data_dirs:
            ensure_data_dirs(merged)
            print(f"  ✓ data/youtube/<subdir>/transcripts·extractions_v2 디렉터리 생성")

    print(f"\n=== 다음 단계 ===")
    print(f"  1. .env 파일 생성:  cp .env.example .env  (OPENAI_API_KEY, WEBSHARE_PROXY_URL)")
    print(f"  2. KR region: python3 scripts/build_krx_whitelist.py")
    print(f"  3. dry-run:   bash scripts/pipeline.sh --dry-run")
    print(f"  4. 첫 실행:   bash scripts/pipeline.sh")
    print(f"  5. 자동화:    bash scheduler/install.sh  (매일 06:00)")


if __name__ == "__main__":
    main()
