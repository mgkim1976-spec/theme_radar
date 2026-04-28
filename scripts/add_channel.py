"""add_channel — 신규 채널 추가 헬퍼.

v2.3+: config/channels.yaml 이 단일 진실 원천. 이 스크립트가 yaml에 추가.

사용:
  python3 scripts/add_channel.py UC<channel_id> <subdir> <lens> "[채널명]" [--apply]

흐름:
  1. 입력 검증 (channel_id 형식, lens가 LENS_PRESETS에 있는지)
  2. 중복 체크
  3. 데이터 디렉터리 미리 생성 (transcripts/, extractions_v2/)
  4. yaml entry 출력
  5. (선택) --apply 면 config/channels.yaml 에 자동 삽입
"""
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import CHANNELS, LENS_PRESETS, YOUTUBE_DATA, CONFIG_DIR

CHANNELS_YAML = CONFIG_DIR / "channels.yaml"


def usage_and_exit(msg: str = ""):
    if msg:
        print(f"❌ {msg}", file=sys.stderr)
    print("Usage: python3 add_channel.py <channel_id> <subdir> <lens> [name] [--apply]", file=sys.stderr)
    print("       lens ∈ {macro, top-down, sector, bottom-up}", file=sys.stderr)
    sys.exit(1)


def validate(channel_id: str, subdir: str, lens: str):
    if not re.match(r"^UC[A-Za-z0-9_-]{22}$", channel_id):
        usage_and_exit(f"channel_id 형식 오류 (UC + 22자 영숫자): {channel_id!r}")
    if not re.match(r"^[a-z][a-z0-9_]*$", subdir):
        usage_and_exit(f"subdir은 소문자/숫자/언더스코어만 (예: yeom_seunghwan): {subdir!r}")
    if lens not in LENS_PRESETS:
        usage_and_exit(f"lens는 {list(LENS_PRESETS.keys())} 중 하나여야 함: {lens!r}")
    if subdir in CHANNELS:
        usage_and_exit(f"이미 등록된 subdir: {subdir}")
    for k, v in CHANNELS.items():
        if v.get("channel_id") == channel_id:
            usage_and_exit(f"이미 등록된 channel_id ({k}): {channel_id}")


def render_yaml_snippet(channel_id: str, subdir: str, lens: str, name: str) -> dict:
    style_hint = {
        "macro": "매크로",
        "top-down": "탑다운",
        "sector": "산업·섹터",
        "bottom-up": "개별 종목",
    }.get(lens, lens)
    return {
        "name": name,
        "channel_id": channel_id,
        "style": style_hint,
        "lens": lens,
    }


def auto_apply_yaml(subdir: str, entry: dict) -> bool:
    """config/channels.yaml 의 channels 섹션에 entry 추가."""
    if not CHANNELS_YAML.exists():
        # 새 yaml 생성
        CHANNELS_YAML.write_text(yaml.safe_dump(
            {"channels": {subdir: entry}}, allow_unicode=True, sort_keys=False
        ))
        return True
    # 기존 yaml 파싱 → 추가 → 다시 쓰기 (기존 헤더 주석 보존)
    text = CHANNELS_YAML.read_text()
    try:
        d = yaml.safe_load(text) or {}
    except Exception:
        return False
    if "channels" not in d:
        d["channels"] = {}
    if subdir in d["channels"]:
        print(f"  ⏩ {subdir} 이미 있음 — 변경 없음")
        return False
    d["channels"][subdir] = entry
    # 헤더 주석 추출 (channels: 줄 이전까지)
    lines = text.splitlines()
    header_lines = []
    for ln in lines:
        if ln.strip().startswith("channels:"):
            break
        header_lines.append(ln)
    header = "\n".join(header_lines).rstrip() + "\n\n"
    body = yaml.safe_dump({"channels": d["channels"]}, allow_unicode=True,
                          sort_keys=False, default_flow_style=False)
    CHANNELS_YAML.write_text(header + body)
    return True


def main():
    args = [a for a in sys.argv[1:] if a != "--apply"]
    apply = "--apply" in sys.argv
    if len(args) < 3:
        usage_and_exit()
    channel_id, subdir, lens = args[0], args[1], args[2]
    name = args[3] if len(args) >= 4 else subdir

    validate(channel_id, subdir, lens)

    # 데이터 디렉터리 사전 생성
    base = YOUTUBE_DATA / subdir
    (base / "transcripts").mkdir(parents=True, exist_ok=True)
    (base / "extractions_v2").mkdir(parents=True, exist_ok=True)
    print(f"  ✓ 데이터 디렉터리 준비됨: {base}")

    entry = render_yaml_snippet(channel_id, subdir, lens, name)
    preset = LENS_PRESETS[lens]
    print(f"\n  Lens preset 적용 → stock_weight={preset['stock_weight']}, "
          f"max_videos_per_run={preset['max_videos_per_run']}")
    print(f"\n--- config/channels.yaml 에 추가할 entry ---")
    print(yaml.safe_dump({subdir: entry}, allow_unicode=True, sort_keys=False))

    if apply:
        if auto_apply_yaml(subdir, entry):
            print(f"  ✓ {CHANNELS_YAML}에 자동 삽입 완료")
            print(f"\n다음 단계:")
            print(f"  bash scripts/pipeline.sh --dry-run   # {len(CHANNELS) + 1}채널 인식 확인")
            print(f"  bash scripts/pipeline.sh             # 다음 실행에서 자동 fetch+extract")
        else:
            print(f"  ⚠️ 자동 삽입 실패 — 위 entry를 수동으로 channels.yaml에 추가하세요")
    else:
        print("  (--apply 옵션을 추가하면 channels.yaml 에 자동 삽입)")


if __name__ == "__main__":
    main()
