"""vault_utils — Obsidian Vault 페이지 공통 유틸.

lint.py + query.py + 향후 모듈이 공유.

기능:
  - iter_pages(types): 페이지 path + frontmatter dict + 본문 yield
  - parse_frontmatter(text): YAML frontmatter dict + body 분리
  - extract_wikilinks(text): [[slug]] / [[path|alias]] 모두 캡처
  - build_index(): {slug: {path, type, title, tags, ...}} 캐시
  - resolve_link(target): 'themes/원전' 같은 wikilink → 실제 path

페이지 슬러그 규칙:
  파일 = VAULT/<folder>/<basename>.md
  슬러그 = "<folder>/<basename>" (확장자·VAULT 경로 제외)
  최상위 파일은 "<basename>"
"""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import yaml

from config import VAULT, COMPILED

INDEX_CACHE_PATH = COMPILED / "vault_index.json"

# 진짜 무시 폴더 (어디서도 안 봄). 첨부·obsidian 시스템.
IGNORE_DIRS = {".obsidian", "_attachments"}
# iter_pages 본문 처리에서만 무시 (존재 체크엔 포함). 템플릿·schema는 페이지 처리 안 하지만 wikilink 대상은 됨.
IGNORE_FOR_BODY_PROCESSING = IGNORE_DIRS | {"_templates", "_schema"}
# 시스템 페이지 (orphan 체크 면제)
SYSTEM_PAGES = {"index", "log", "README", "themes/_dashboard"}

# 페이지 타입별 frontmatter 필수 필드
TYPE_REQUIRED_FIELDS = {
    "youtuber":     ["name", "channel_id", "last_updated", "tags"],
    "theme":        ["canonical_name", "slug", "lifecycle", "last_updated", "tags"],
    "methodology":  ["last_updated", "tags"],
    "catalyst":     ["date", "category", "last_updated", "tags"],
    "company":      ["last_updated", "tags"],
    "market_regime":["last_updated", "tags"],
    "regime":       ["last_updated", "tags"],
    "playbook":     ["last_updated", "tags"],
    "decision":     ["question", "asked_at", "sources", "status", "tags"],
    "question":     ["category", "severity", "status", "detected_at", "tags"],
    "dashboard":    ["last_updated", "tags"],
}


@dataclass
class Page:
    slug: str            # "themes/원전_전력설비"
    path: Path           # 절대 경로
    fm: dict             # frontmatter
    body: str            # frontmatter 제외 본문
    folder: str = ""     # "themes" / "" (최상위)
    name: str = ""       # 파일 basename (확장자 제외)

    @property
    def type(self) -> str:
        return self.fm.get("type", "unknown")

    @property
    def tags(self) -> list[str]:
        t = self.fm.get("tags") or []
        return t if isinstance(t, list) else [t]

    @property
    def title(self) -> str:
        # H1 or frontmatter name/title
        m = re.search(r"^# (.+)$", self.body, re.MULTILINE)
        if m:
            return m.group(1).strip()
        return self.fm.get("name") or self.fm.get("title") or self.name


_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)$", re.DOTALL)
_WIKILINK_RE = re.compile(r"\[\[([^\]\|]+)(?:\|[^\]]*)?\]\]")


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """YAML frontmatter + body. frontmatter 없으면 ({}, text)."""
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        fm = {}
    if not isinstance(fm, dict):
        fm = {}
    return fm, m.group(2)


def extract_wikilinks(text: str) -> list[str]:
    """본문에서 [[slug]] / [[path|alias]] 추출. 슬러그만 반환.
    table cell의 `\\|` escape로 인한 trailing `\\` 제거."""
    return [m.strip().rstrip("\\").strip() for m in _WIKILINK_RE.findall(text)]


def _iter_md_files(for_body: bool = False) -> Iterator[Path]:
    """모든 vault .md 순회. for_body=True면 _schema 등 본문 처리 제외 폴더도 skip."""
    if not VAULT.exists():
        return
    skip = IGNORE_FOR_BODY_PROCESSING if for_body else IGNORE_DIRS
    for p in VAULT.rglob("*.md"):
        rel = p.relative_to(VAULT)
        parts = rel.parts
        if any(d in skip for d in parts):
            continue
        yield p


def slug_from_path(p: Path) -> str:
    rel = p.relative_to(VAULT).with_suffix("")
    return str(rel)


def iter_pages(types: list[str] | None = None) -> Iterator[Page]:
    """본문 처리용 페이지 iter (_schema·_templates 제외). types 지정 시 type 필터."""
    for p in _iter_md_files(for_body=True):
        try:
            text = p.read_text()
        except Exception:
            continue
        fm, body = parse_frontmatter(text)
        rel = p.relative_to(VAULT).with_suffix("")
        slug = str(rel)
        folder = str(rel.parent) if rel.parent != Path(".") else ""
        page = Page(slug=slug, path=p, fm=fm, body=body, folder=folder, name=rel.name)
        if types and page.type not in types:
            continue
        yield page


def all_slugs() -> set[str]:
    return {slug_from_path(p) for p in _iter_md_files()}


def resolve_link(target: str, slugs: set[str]) -> str | None:
    """wikilink target → 실제 슬러그. None이면 broken.

    매칭 우선순위:
      1. 정확 일치
      2. basename 일치 (folder 생략된 링크 허용)
    """
    target = target.strip()
    if target in slugs:
        return target
    # basename 매칭
    candidates = [s for s in slugs if s.split("/")[-1] == target]
    if len(candidates) == 1:
        return candidates[0]
    return None


def build_index() -> dict:
    """{slug: {path, type, title, tags, lifecycle, summary}}. 캐시 저장."""
    out: dict[str, dict] = {}
    for page in iter_pages():
        first_para = page.body.split("\n\n", 2)[0:2]
        summary = " ".join(first_para).strip()[:160]
        out[page.slug] = {
            "type": page.type,
            "title": page.title[:80],
            "tags": page.tags,
            "lifecycle": page.fm.get("lifecycle"),
            "channels": page.fm.get("channels"),
            "summary": summary,
            "folder": page.folder,
        }
    COMPILED.mkdir(parents=True, exist_ok=True)
    INDEX_CACHE_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def load_index() -> dict:
    if INDEX_CACHE_PATH.exists():
        try:
            return json.loads(INDEX_CACHE_PATH.read_text())
        except Exception:
            pass
    return build_index()
