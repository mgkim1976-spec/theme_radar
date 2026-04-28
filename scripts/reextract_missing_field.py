"""reextract_missing_field — 스키마 누락 필드 검출 → 해당 추출 삭제.

배경: 스키마에 새 필드(예: event_type)를 추가하면 기존 추출 파일에는 그 필드가
없다. 일관성을 원하면 모두 재추출해야 하지만 이미 추출된 파일을 그대로 두면
yt_extract_batch가 idempotent skip 한다 → 영원히 누락.

이 스크립트는:
  1. 모든 채널의 extractions_v2/ 를 스캔
  2. themes[]에서 필드가 빠진 파일을 찾음
  3. (--apply 면) 삭제 → 다음 pipeline 실행 시 yt_extract_batch가 재처리

기본은 dry-run. --apply 로만 실제 삭제. 매우 보수적인 동작.

사용:
  python3 reextract_missing_field.py                          # event_type 누락 dry-run
  python3 reextract_missing_field.py --apply                   # 실제 삭제
  python3 reextract_missing_field.py --field=tickers --apply   # 다른 필드
  python3 reextract_missing_field.py --channel=86bunga         # 한 채널만
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import CHANNELS, channel_paths, EXTRACTION_MODEL


def needs_reextract(extraction: dict, field: str) -> bool:
    """themes[]의 모든 항목이 field를 가지면 OK. 하나라도 빠지면 재추출 대상."""
    themes = extraction.get("themes") or []
    if not themes:
        return False  # 빈 추출은 그대로 둠 (uncertain 등)
    return any(field not in t for t in themes)


def scan_channel(subdir: str, field: str) -> list[Path]:
    ext_dir = channel_paths(subdir)["extractions"]
    if not ext_dir.exists():
        return []
    stale: list[Path] = []
    for f in sorted(ext_dir.glob(f"*_{EXTRACTION_MODEL}.json")):
        try:
            e = json.loads(f.read_text())
        except Exception:
            continue
        if needs_reextract(e, field):
            stale.append(f)
    return stale


def main():
    field = "event_type"
    apply = False
    only_channel = None
    for a in sys.argv[1:]:
        if a == "--apply":
            apply = True
        elif a.startswith("--field="):
            field = a.split("=", 1)[1]
        elif a.startswith("--channel="):
            only_channel = a.split("=", 1)[1]

    total_stale = 0
    total_files = 0
    by_channel: dict[str, int] = {}
    stale_paths: list[Path] = []

    for subdir in CHANNELS:
        if only_channel and subdir != only_channel:
            continue
        ext_dir = channel_paths(subdir)["extractions"]
        n_total = len(list(ext_dir.glob(f"*_{EXTRACTION_MODEL}.json"))) if ext_dir.exists() else 0
        stale = scan_channel(subdir, field)
        total_files += n_total
        total_stale += len(stale)
        by_channel[subdir] = len(stale)
        stale_paths.extend(stale)

    print(f"[reextract] field={field!r}  mode={'APPLY' if apply else 'DRY-RUN'}")
    print(f"[reextract] 총 추출 {total_files}편 중 {total_stale}편이 {field!r} 누락:")
    for subdir, n in by_channel.items():
        if n > 0:
            print(f"  - {subdir}: {n}편")

    if total_stale == 0:
        print("[reextract] 누락 없음 — 스킵")
        return

    est_cost = total_stale * 0.002
    print(f"[reextract] 재추출 예상 비용: ~${est_cost:.2f}")

    if not apply:
        print("[reextract] dry-run — 실제 삭제하려면 --apply 추가")
        return

    deleted = 0
    for p in stale_paths:
        try:
            p.unlink()
            deleted += 1
        except Exception as ex:
            print(f"  ! {p.name}: {ex}")
    print(f"[reextract] {deleted}편 삭제 완료")
    print(f"[reextract] 다음 단계: bash scripts/pipeline.sh "
          f"--skip-fetch --skip-catalysts --skip-reports "
          f"--skip-themes --skip-methodology --skip-wiki --skip-dashboard")


if __name__ == "__main__":
    main()
