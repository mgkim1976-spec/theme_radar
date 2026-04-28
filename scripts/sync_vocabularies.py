"""sync_vocabularies — 외부 vocabulary를 theme_radar/data/reference/vocabularies/로 snapshot 복사.

설계 의도:
  - cross-project 의존성 회피. 외부 프로젝트가 사라져도 theme_radar 정상 동작.
  - sha256 해시 + provenance 메타로 drift 검출.
  - 수동 sync (분기 1회 정도면 충분, 어휘는 안정적).

사용:
  python3 scripts/sync_vocabularies.py            # diff 확인 (dry-run)
  python3 scripts/sync_vocabularies.py --apply    # 실제 복사 + provenance 갱신
  python3 scripts/sync_vocabularies.py --add SRC NAME   # 새 vocabulary 추가
"""
import hashlib
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import REFERENCE

VOCAB_DIR = REFERENCE / "vocabularies"
PROVENANCE_PATH = VOCAB_DIR / "_provenance.json"

# 기본 등록 vocabulary 목록. 새로 추가 시 이 dict에만 한 줄 더.
# Snapshot registry — 외부 vocabulary source 경로는 config/project.yaml 의
# integrations.vocabulary_snapshots.sources 에서 로드. 기본값은 빈 string (해당 통합 비활성).
# 다른 사용자: 자기 환경의 source 경로를 project.yaml 에 적으면 자동 vendoring 됨.
def _build_registry() -> dict:
    from config import INTEGRATIONS
    voc_cfg = (INTEGRATIONS.get("vocabulary_snapshots") or {})
    if not voc_cfg.get("enabled"):
        return {}
    sources = voc_cfg.get("sources") or {}
    registry = {}
    catalog = {
        "macro_event": ("macro_event_vocabulary.snapshot.json",
                        "42 매크로 이벤트 (severity·direction·impact·keywords_ko·causal_chain·base_rate)",
                        None),
        "corporate_event": ("corporate_event_vocabulary.snapshot.json",
                            "기업 단위 이벤트 (실적·M&A·자사주·지배구조·신사업 등)",
                            None),
        "regime_state": ("regime_state.snapshot.json",
                         "현재 시장 regime (FRED 3-axis z-score 기반)",
                         "md_frontmatter"),
        "phase_kb": ("phase_kb.snapshot.json",
                     "30 historical macro events × 6-phase 자산 반응 KB",
                     None),
    }
    for key, src in sources.items():
        if not src:
            continue
        if key in catalog:
            local_name, desc, transform = catalog[key]
            entry = {"source": src, "description": desc}
            if transform:
                entry["transform"] = transform
            registry[local_name] = entry
    return registry


REGISTRY = _build_registry()


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def load_provenance() -> dict:
    if PROVENANCE_PATH.exists():
        try:
            return json.loads(PROVENANCE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_provenance(prov: dict):
    VOCAB_DIR.mkdir(parents=True, exist_ok=True)
    PROVENANCE_PATH.write_text(json.dumps(prov, ensure_ascii=False, indent=2))


def diff_one(name: str, info: dict, prov_entry: dict) -> tuple[str, dict]:
    """반환: (status, new_provenance_entry)
    status ∈ {missing_source, missing_local, in_sync, drift, new}"""
    src = Path(info["source"])
    local = VOCAB_DIR / name
    if not src.exists():
        return "missing_source", {"source": str(src), "error": "source not found"}

    src_sha = sha256_of(src)
    local_sha = sha256_of(local) if local.exists() else None

    new_meta = {
        "source": str(src),
        "description": info.get("description", ""),
        "transform": info.get("transform"),
        "source_sha256": src_sha,
        "source_size": src.stat().st_size,
    }

    if local_sha is None:
        return "new", new_meta
    # transform된 경우 source_sha256만 비교 (local은 transform 결과라 다름)
    if info.get("transform"):
        if prov_entry.get("source_sha256") == src_sha:
            return "in_sync", prov_entry
        return "drift", new_meta
    if prov_entry.get("source_sha256") == src_sha and local_sha == prov_entry.get("local_sha256"):
        return "in_sync", prov_entry
    return "drift", new_meta


def _md_frontmatter_to_json(md_path: Path) -> dict:
    """SIGNAL-REGIME.md 처럼 frontmatter만 의미 있는 .md → dict."""
    import re
    text = md_path.read_text()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {"_error": "no frontmatter"}
    import yaml as _yaml
    try:
        return _yaml.safe_load(m.group(1)) or {}
    except Exception as ex:
        return {"_error": str(ex)}


def apply_one(name: str, info: dict) -> dict:
    src = Path(info["source"])
    local = VOCAB_DIR / name
    VOCAB_DIR.mkdir(parents=True, exist_ok=True)
    transform = info.get("transform")
    if transform == "md_frontmatter":
        # markdown frontmatter parse → JSON
        data = _md_frontmatter_to_json(src)
        data["_synced_at"] = datetime.now().isoformat(timespec="seconds")
        data["_source"] = str(src)
        local.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        shutil.copy2(src, local)
    sha = sha256_of(local)
    return {
        "source": str(src),
        "description": info.get("description", ""),
        "transform": transform,
        "source_sha256": sha256_of(src) if src.exists() else None,
        "local_sha256": sha,
        "source_size": src.stat().st_size,
        "synced_at": datetime.now().isoformat(timespec="seconds"),
    }


def main():
    apply = "--apply" in sys.argv
    if "--add" in sys.argv:
        i = sys.argv.index("--add")
        if i + 2 >= len(sys.argv):
            print("Usage: --add <source_path> <local_filename>", file=sys.stderr)
            sys.exit(1)
        src, name = sys.argv[i + 1], sys.argv[i + 2]
        REGISTRY[name] = {"source": src, "description": "manual add"}

    prov = load_provenance()
    summary = []
    changes = False

    for name, info in REGISTRY.items():
        prov_entry = prov.get(name, {})
        status, new_meta = diff_one(name, info, prov_entry)
        summary.append((name, status, new_meta))
        if status in {"new", "drift"}:
            changes = True
            if apply:
                prov[name] = apply_one(name, info)

    print(f"[sync_vocab] mode={'APPLY' if apply else 'DRY-RUN'}")
    for name, status, meta in summary:
        marker = {
            "in_sync": "✓",
            "new": "+",
            "drift": "Δ",
            "missing_source": "✗",
            "missing_local": "?",
        }.get(status, "?")
        print(f"  {marker} {status:15} {name}")
        if status in {"new", "drift", "missing_source"}:
            print(f"      source: {meta.get('source','?')}")

    if changes and apply:
        save_provenance(prov)
        print(f"\n[sync_vocab] ✓ provenance 갱신: {PROVENANCE_PATH}")
    elif changes:
        print("\n[sync_vocab] dry-run — 적용하려면 --apply 추가")
    else:
        print("\n[sync_vocab] 모두 in-sync — 변경 없음")


if __name__ == "__main__":
    main()
