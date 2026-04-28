"""lint — Vault 정합성 자동 검사 (static, LLM 미사용).

체크 항목:
  1. broken_link    — [[slug]] 가 존재하지 않는 파일을 참조
  2. orphan         — 어떤 페이지에서도 링크되지 않음 (시스템 페이지 제외)
  3. schema_drift   — frontmatter 필수 필드 누락 (type별)
  4. dictionary_gap — canonical_themes 중 multi-mention ≥10 인데 page 없음
  5. stale_methodology — methodologies/* 가 30일 이상 미갱신

기본 dry-run (콘솔 요약). `--apply` 면 questions/ 자동 등록.
LLM 미사용. 비용 0.

사용:
  python3 lint.py                 # 콘솔 요약
  python3 lint.py --apply         # questions/ 자동 등록
  python3 lint.py --severity=high # 특정 severity만
"""
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import vault_utils as vu
from config import VAULT, COMPILED


SEVERITY_BY_CATEGORY = {
    "broken_link":      "high",
    "schema_drift":     "medium",
    "dictionary_gap":   "medium",
    "orphan":           "low",
    "stale_methodology":"low",
}


def check_broken_links(pages: list[vu.Page], slugs: set[str]) -> list[dict]:
    findings = []
    for p in pages:
        for raw in vu.extract_wikilinks(p.body):
            target = vu.resolve_link(raw, slugs)
            if not target:
                findings.append({
                    "category": "broken_link",
                    "from": p.slug,
                    "target": raw,
                    "msg": f"[[{raw}]] 가 vault에 없음",
                })
    return findings


def check_orphans(pages: list[vu.Page]) -> list[dict]:
    inbound: dict[str, int] = defaultdict(int)
    for p in pages:
        for raw in vu.extract_wikilinks(p.body):
            inbound[raw.strip()] += 1
            inbound[raw.strip().split("/")[-1]] += 1  # basename matching

    findings = []
    for p in pages:
        if p.slug in vu.SYSTEM_PAGES:
            continue
        if p.fm.get("type") in {"dashboard", "question"}:
            continue
        if p.slug.split("/")[-1].startswith("_"):
            continue
        # 자동 생성 페이지(theme/catalyst auto-ingested)는 orphan 면제
        # — 의도된 standalone, dashboard·index에서 동적으로 노출
        if "auto-ingested" in p.tags or "auto-synth" in p.tags:
            continue
        # basename 매칭도 카운트
        if inbound.get(p.slug, 0) + inbound.get(p.name, 0) == 0:
            findings.append({
                "category": "orphan",
                "from": p.slug,
                "msg": f"어떤 페이지도 [[{p.slug}]] 를 참조하지 않음",
            })
    return findings


def check_schema(pages: list[vu.Page]) -> list[dict]:
    findings = []
    for p in pages:
        t = p.fm.get("type")
        if not t:
            findings.append({
                "category": "schema_drift",
                "from": p.slug,
                "msg": "frontmatter에 type 없음",
            })
            continue
        required = vu.TYPE_REQUIRED_FIELDS.get(t)
        if required is None:
            continue  # 알 수 없는 type은 건너뜀
        missing = [f for f in required if f not in p.fm]
        if missing:
            findings.append({
                "category": "schema_drift",
                "from": p.slug,
                "msg": f"type={t} 필수 필드 누락: {missing}",
            })
    return findings


def check_dictionary_gap(pages: list[vu.Page], slugs: set[str]) -> list[dict]:
    """multi-mention ≥10 인 canonical theme 중 page 없는 항목."""
    dict_path = COMPILED / "theme_dictionary.json"
    if not dict_path.exists():
        return []
    try:
        d = json.loads(dict_path.read_text())
    except Exception:
        return []
    findings = []
    for canon, info in d.get("canonical_themes", {}).items():
        if info.get("total_mentions", 0) < 10:
            continue
        slug = f"themes/{info.get('slug')}"
        if slug in slugs or slug.split("/")[-1] in {s.split("/")[-1] for s in slugs}:
            continue
        findings.append({
            "category": "dictionary_gap",
            "from": "(none)",
            "target": slug,
            "msg": f"canonical theme '{canon}' (mentions={info['total_mentions']}) "
                   f"가 dictionary에 있는데 page 없음",
        })
    return findings


def check_stale_methodology(pages: list[vu.Page]) -> list[dict]:
    """methodologies/*_pattern.md 또는 수동 작성된 페이지 30일+ 미갱신."""
    findings = []
    cutoff = datetime.now() - timedelta(days=30)
    for p in pages:
        if not p.slug.startswith("methodologies/"):
            continue
        last = p.fm.get("last_updated")
        if not last:
            continue
        try:
            d = datetime.fromisoformat(str(last))
        except Exception:
            continue
        if d < cutoff:
            findings.append({
                "category": "stale_methodology",
                "from": p.slug,
                "msg": f"last_updated={last} ({(datetime.now() - d).days}일 전)",
            })
    return findings


def write_question_pages(findings: list[dict]) -> int:
    """questions/{date}_{category}_{slug}.md 자동 등록."""
    qdir = VAULT / "questions"
    qdir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    written = 0
    for f in findings:
        cat = f["category"]
        from_ = f.get("from", "global").replace("/", "_")
        target = f.get("target", "")
        slug_part = (target or from_)[:60].replace("/", "_")
        qpath = qdir / f"{today}_{cat}_{slug_part}.md"
        if qpath.exists():
            continue
        sev = SEVERITY_BY_CATEGORY.get(cat, "medium")
        related = []
        if "from" in f and f["from"] != "(none)":
            related.append(f"[[{f['from']}]]")
        if "target" in f:
            related.append(f"target: `{f['target']}`")
        body = f"""---
type: question
category: {cat}
severity: {sev}
status: open
detected_at: {today}
related: {related}
tags: [question, lint, {cat}]
---

# Lint: {cat}

## 발견
{f['msg']}

## 관련
{chr(10).join('- ' + r for r in related) if related else '_(없음)_'}

## 권장 조치
- broken_link: 링크 대상 페이지를 만들거나 wikilink 수정
- orphan: 다른 페이지에서 참조 추가, 또는 의도된 standalone이면 무시
- schema_drift: frontmatter 보강
- dictionary_gap: theme_pages_gen 재실행 (자동 채워질 가능성)
- stale_methodology: methodology_synth --force 또는 수동 갱신
"""
        qpath.write_text(body)
        written += 1
    return written


def main():
    apply = "--apply" in sys.argv
    severity_filter = None
    for a in sys.argv[1:]:
        if a.startswith("--severity="):
            severity_filter = a.split("=", 1)[1]

    pages = list(vu.iter_pages())
    body_slugs = {p.slug for p in pages}
    all_slugs = vu.all_slugs()  # _schema 등 포함 (broken_link 존재 체크용)

    all_findings: list[dict] = []
    all_findings += check_broken_links(pages, all_slugs)
    all_findings += check_orphans(pages)
    all_findings += check_schema(pages)
    all_findings += check_dictionary_gap(pages, all_slugs)
    all_findings += check_stale_methodology(pages)

    # severity 부여
    for f in all_findings:
        f["severity"] = SEVERITY_BY_CATEGORY.get(f["category"], "medium")

    if severity_filter:
        all_findings = [f for f in all_findings if f["severity"] == severity_filter]

    by_cat = Counter(f["category"] for f in all_findings)
    by_sev = Counter(f["severity"] for f in all_findings)

    print(f"[lint] {len(pages)} 페이지 검사 완료")
    print(f"[lint] 총 발견: {len(all_findings)}건")
    if by_cat:
        print("  by category:")
        for c, n in by_cat.most_common():
            print(f"    {c:24} {n}")
        print("  by severity:")
        for s, n in by_sev.most_common():
            print(f"    {s:24} {n}")

    # 샘플 5건 출력
    if all_findings:
        print("\n[lint] 샘플:")
        for f in all_findings[:5]:
            print(f"  [{f['severity']}/{f['category']}] {f.get('from','')} — {f['msg'][:90]}")
        if len(all_findings) > 5:
            print(f"  ... 외 {len(all_findings) - 5}건")

    if apply and all_findings:
        n = write_question_pages(all_findings)
        print(f"\n[lint] questions/ 에 {n}개 페이지 등록")
    elif all_findings:
        print(f"\n[lint] dry-run — 등록하려면 --apply 추가")


if __name__ == "__main__":
    main()
