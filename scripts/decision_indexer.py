"""decision_indexer — Loop B: Query 결과의 wiki 환류.

query.py가 decisions/{slug}.md 를 저장한 직후 이 모듈을 호출하면:
  1. 인용된 source 페이지 각각에 AUTO_DECISION_LINKS 블록 백링크 추가
     → 사용자가 source 페이지 읽을 때 "이 페이지를 인용한 결정들" 자동 노출
  2. data/reference/compiled/citation_index.json 갱신
     → 자주 인용되는 페이지 = high-signal. dashboard에서 우선 노출 가능.

CLI 사용 (단독):
  python3 decision_indexer.py --rebuild       # decisions/ 전수 스캔, 인덱스 + 백링크 재구축
  python3 decision_indexer.py --slug=YYYYMMDD_xxx --sources=slug1,slug2,...  # 단일 추가
"""
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import VAULT, COMPILED

DECISIONS_DIR = VAULT / "decisions"
CITATION_INDEX_PATH = COMPILED / "citation_index.json"

BACKLINK_START = "<!-- AUTO_DECISION_LINKS_START -->"
BACKLINK_END = "<!-- AUTO_DECISION_LINKS_END -->"

_SLUG_RE = re.compile(r"^[\w/\-]+$")


def _resolve_path(slug: str) -> Path | None:
    """vault slug → 실제 파일 경로. 없으면 None."""
    p = VAULT / f"{slug}.md"
    if p.exists():
        return p
    # basename 매칭 (slug에 폴더 빠진 경우)
    candidates = list(VAULT.rglob(f"{slug.split('/')[-1]}.md"))
    if len(candidates) == 1:
        return candidates[0]
    return None


def _add_backlink(source_path: Path, decision_slug: str):
    """source 페이지에 AUTO_DECISION_LINKS 블록을 보장하고 decision 추가."""
    text = source_path.read_text()
    new_link = f"- [[{decision_slug}]]"
    if BACKLINK_START in text and BACKLINK_END in text:
        before = text.split(BACKLINK_START)[0]
        after_part = text.split(BACKLINK_END)[1]
        block_inner = text.split(BACKLINK_START)[1].split(BACKLINK_END)[0]
        if new_link in block_inner:
            return False  # 이미 있음
        block_inner = block_inner.rstrip() + f"\n{new_link}\n"
        text = before + BACKLINK_START + block_inner + BACKLINK_END + after_part
    else:
        # AUTO 블록 없음 → 끝에 append
        text = text.rstrip() + f"\n\n## 관련 결정 (자동)\n\n{BACKLINK_START}\n{new_link}\n{BACKLINK_END}\n"
    source_path.write_text(text)
    return True


def index_decision(decision_slug: str, sources: list[str]) -> dict:
    """단일 decision의 sources에 backlink 추가 + citation 카운트 반환.
    return: {sources_added, sources_skipped, sources_missing}"""
    added, skipped, missing = [], [], []
    for s in sources:
        s = s.strip()
        if not s or not _SLUG_RE.match(s):
            continue
        p = _resolve_path(s)
        if not p:
            missing.append(s)
            continue
        if _add_backlink(p, decision_slug):
            added.append(s)
        else:
            skipped.append(s)
    return {"added": added, "skipped": skipped, "missing": missing}


def load_citation_index() -> dict:
    if CITATION_INDEX_PATH.exists():
        try:
            return json.loads(CITATION_INDEX_PATH.read_text())
        except Exception:
            pass
    return {"version": 1, "counts": {}}


def save_citation_index(idx: dict):
    idx["generated_at"] = datetime.now().isoformat(timespec="seconds")
    COMPILED.mkdir(parents=True, exist_ok=True)
    CITATION_INDEX_PATH.write_text(json.dumps(idx, ensure_ascii=False, indent=2))


def update_citation_counts(sources: list[str], idx: dict | None = None) -> dict:
    if idx is None:
        idx = load_citation_index()
    counts = idx.setdefault("counts", {})
    for s in sources:
        counts[s] = counts.get(s, 0) + 1
    return idx


def parse_decision_sources(decision_path: Path) -> list[str]:
    """decision 페이지의 frontmatter에서 sources 리스트 추출."""
    text = decision_path.read_text()
    m = re.search(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return []
    fm_text = m.group(1)
    in_sources = False
    out = []
    for line in fm_text.splitlines():
        if line.startswith("sources:"):
            in_sources = True
            continue
        if in_sources:
            stripped = line.strip()
            if stripped.startswith("- "):
                out.append(stripped[2:].strip())
            elif not line.startswith(" ") and not line.startswith("\t"):
                # 다음 frontmatter 키
                in_sources = False
    return out


def rebuild_all() -> dict:
    """decisions/ 전수 스캔 → 모든 backlink + citation_index 재구축.
    이미 있는 backlink는 스킵 (idempotent)."""
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    idx = {"version": 1, "counts": {}}
    n_decisions = 0
    n_added_total = 0
    for d_path in sorted(DECISIONS_DIR.glob("*.md")):
        sources = parse_decision_sources(d_path)
        if not sources:
            continue
        n_decisions += 1
        slug = f"decisions/{d_path.stem}"
        result = index_decision(slug, sources)
        n_added_total += len(result["added"])
        for s in sources:
            p = _resolve_path(s)
            if p:
                idx["counts"][s] = idx["counts"].get(s, 0) + 1
    save_citation_index(idx)
    return {
        "n_decisions": n_decisions,
        "n_backlinks_added": n_added_total,
        "n_unique_sources_cited": len(idx["counts"]),
    }


def main():
    args = sys.argv[1:]
    if "--rebuild" in args:
        r = rebuild_all()
        print(f"[decision_indexer] rebuild — {r}")
        return
    slug = None
    sources_str = None
    for a in args:
        if a.startswith("--slug="):
            slug = a.split("=", 1)[1]
        elif a.startswith("--sources="):
            sources_str = a.split("=", 1)[1]
    if not slug or not sources_str:
        print("Usage: --rebuild | --slug=X --sources=a,b,c")
        return
    sources = [s.strip() for s in sources_str.split(",") if s.strip()]
    result = index_decision(slug, sources)
    idx = update_citation_counts(sources)
    save_citation_index(idx)
    print(f"[decision_indexer] {slug}: added={len(result['added'])}, "
          f"skipped={len(result['skipped'])}, missing={len(result['missing'])}")


if __name__ == "__main__":
    main()
