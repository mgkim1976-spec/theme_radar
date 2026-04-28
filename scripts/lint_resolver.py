"""lint_resolver — Loop C: questions/ 자동 해결.

lint.py가 questions/{date}_{cat}_{slug}.md 페이지로 등록한 문제 중
auto-resolvable 항목을 LLM/룰 조합으로 해결.

자동 해결 가능한 카테고리:
  - broken_link  : LLM이 의도 파악 → 가까운 슬러그 매칭 또는 stub 페이지 생성
  - schema_drift : frontmatter 필수 필드 자동 추가 (page 본문에서 추론 가능한 경우)

해결 안 되는 카테고리(orphan, dictionary_gap, stale_methodology)는 그대로 둠.

해결된 question 페이지는 status: resolved 로 frontmatter 갱신 + resolution 섹션 추가.

CLI:
  python3 lint_resolver.py                  # dry-run, 해결 시도 결과만 출력
  python3 lint_resolver.py --apply          # 실제 적용
  python3 lint_resolver.py --category=broken_link --apply
"""
import json
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
import vault_utils as vu
from config import VAULT
from llm_client import chat_json, DEFAULT_MODEL

QUESTIONS_DIR = VAULT / "questions"


def load_questions(category_filter: str | None = None) -> list[dict]:
    """open status questions만."""
    out = []
    for p in sorted(QUESTIONS_DIR.glob("*.md")):
        try:
            text = p.read_text()
        except Exception:
            continue
        fm, body = vu.parse_frontmatter(text)
        if fm.get("status") != "open":
            continue
        cat = fm.get("category", "")
        if category_filter and cat != category_filter:
            continue
        out.append({"path": p, "fm": fm, "body": body, "text": text})
    return out


def llm_resolve_broken_link(target: str, slugs: set[str]) -> dict:
    """LLM이 broken link target에 가까운 실제 슬러그 추천.
    return: {action, slug?, reason}"""
    # 후보: basename 비슷한 슬러그
    base = target.split("/")[-1]
    candidates = sorted([s for s in slugs if base in s or s.split("/")[-1] in target])[:30]
    if not candidates:
        # 같은 폴더의 모든 페이지
        folder = target.rsplit("/", 1)[0] if "/" in target else ""
        if folder:
            candidates = sorted([s for s in slugs if s.startswith(folder + "/")])[:30]

    SYS = ("당신은 Obsidian wiki의 broken link를 해결합니다. "
           "주어진 target과 후보 슬러그 리스트를 보고, 의도된 페이지를 추천하거나, "
           "stub 페이지 생성을 권장합니다.")
    user = f"""# Target (broken link)
{target}

# 후보 슬러그 ({len(candidates)})
```json
{json.dumps(candidates, ensure_ascii=False)}
```

# 작업
응답은 JSON만:
{{"action": "fix" | "stub" | "skip",
  "slug": "권장 슬러그 (action=fix일 때)",
  "reason": "한 문장 이유"}}

가이드:
- target이 후보 중 어느 하나의 오탈자/표기 변형이면 → action: "fix", slug: 정확한 후보
- 후보가 없거나 명백히 다른 의미면 → action: "stub" (stub 페이지 생성 필요)
- 판단 어려우면 → action: "skip"
"""
    try:
        out, r = chat_json(SYS, user, model=DEFAULT_MODEL)
        return out
    except Exception as ex:
        return {"action": "skip", "reason": f"LLM error: {ex}"}


def fix_wikilink_in_pages(old_target: str, new_slug: str) -> int:
    """모든 vault 페이지에서 [[old_target]] / [[old_target|...]] → [[new_slug...]]"""
    pattern = re.compile(rf"\[\[{re.escape(old_target)}(\|[^\]]*)?\]\]")
    replacement = lambda m: f"[[{new_slug}{m.group(1) or ''}]]"
    n = 0
    for p in vu._iter_md_files():
        try:
            text = p.read_text()
        except Exception:
            continue
        new_text, count = pattern.subn(replacement, text)
        if count:
            p.write_text(new_text)
            n += count
    return n


def create_stub_page(slug: str) -> bool:
    """누락 슬러그에 stub 페이지 생성. type별 필수 frontmatter 모두 채워서 schema_drift 회피."""
    p = VAULT / f"{slug}.md"
    if p.exists():
        return False
    p.parent.mkdir(parents=True, exist_ok=True)
    name = slug.split("/")[-1]
    folder = slug.rsplit("/", 1)[0] if "/" in slug else "misc"
    type_guess = {
        "themes": "theme",
        "methodologies": "methodology",
        "youtubers": "youtuber",
        "catalysts": "catalyst",
        "_schema": "schema",
        "playbooks": "playbook",
        "decisions": "decision",
        "questions": "question",
        "companies": "company",
        "market_regimes": "regime",
    }.get(folder, "misc")
    today = datetime.now().date().isoformat()

    # type별 필수 필드 모두 채워서 lint schema_drift 회피
    fm_lines = [f"type: {type_guess}", f"slug: {slug}", f"last_updated: {today}",
                f"tags: [{type_guess}, stub, auto-created]", "status: stub"]
    if type_guess == "theme":
        fm_lines.insert(1, f"canonical_name: {name}")
        fm_lines.append("lifecycle: Unknown")
    elif type_guess == "youtuber":
        fm_lines.insert(1, f"name: {name}")
        fm_lines.insert(2, "channel_id: UNKNOWN")
    elif type_guess == "catalyst":
        fm_lines.append(f"date: {today}")
        fm_lines.append("category: misc")
    elif type_guess == "decision":
        fm_lines.append(f'question: "(stub)"')
        fm_lines.append(f"asked_at: {today}")
        fm_lines.append("sources: []")
    elif type_guess == "question":
        fm_lines.append("category: misc")
        fm_lines.append("severity: low")
        fm_lines.append(f"detected_at: {today}")

    content = f"""---
{chr(10).join(fm_lines)}
---

# {name.replace('_', ' ')}

> 🚧 lint_resolver가 자동 생성한 stub. broken_link 발생 시 자리 채움 용도.
> 실제 내용은 사용자가 채우거나 ingest로 자동 채워질 예정.

<!-- STUB_AUTO_CREATED -->
"""
    p.write_text(content)
    return True


def fix_schema_drift(question: dict) -> dict:
    """schema_drift question → 대상 페이지의 frontmatter 자동 보강 시도.
    return: {action, applied?: list, reason}"""
    body = question["body"]
    # "frontmatter에 type 없음" 또는 "type=X 필수 필드 누락: [...]"
    related = question["fm"].get("related") or []
    target_slug = None
    for r in related:
        if isinstance(r, str):
            m = re.match(r"\[\[(.+?)\]\]", r)
            if m:
                target_slug = m.group(1)
                break
    if not target_slug:
        return {"action": "skip", "reason": "관련 페이지 슬러그 추출 실패"}

    target_path = vu.resolve_link(target_slug, vu.all_slugs())
    if not target_path:
        return {"action": "skip", "reason": f"slug {target_slug} 미발견"}
    p = VAULT / f"{target_path}.md"
    if not p.exists():
        return {"action": "skip", "reason": f"파일 없음: {p}"}

    text = p.read_text()
    fm, page_body = vu.parse_frontmatter(text)

    # 메시지에서 누락 필드 추출
    msg = ""
    m = re.search(r"필수 필드 누락:\s*\[(.*?)\]", body)
    missing_fields = []
    if m:
        missing_fields = [f.strip().strip("'\"") for f in m.group(1).split(",")]

    today = datetime.now().date().isoformat()
    applied = []
    for f in missing_fields:
        if f in fm:
            continue
        # heuristic 기본값
        if f == "last_updated":
            fm[f] = today
        elif f == "tags":
            fm[f] = [target_slug.split("/")[0] if "/" in target_slug else "misc", "auto-resolved"]
        elif f == "name":
            # 본문 H1
            mh = re.search(r"^# (.+)$", page_body, re.MULTILINE)
            fm[f] = mh.group(1).strip() if mh else target_slug.split("/")[-1]
        elif f == "channel_id":
            fm[f] = "UNKNOWN"
        elif f == "slug":
            fm[f] = target_slug
        elif f == "lifecycle":
            fm[f] = "Unknown"
        else:
            continue  # 자동 추론 불가
        applied.append(f)

    if not applied:
        return {"action": "skip", "reason": "자동 추론 가능 필드 없음"}

    new_fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    new_text = f"---\n{new_fm_text}\n---\n{page_body}"
    p.write_text(new_text)
    return {"action": "fix", "applied": applied, "reason": f"frontmatter 보강: {applied}"}


def mark_resolved(question: dict, resolution: dict):
    """question 페이지의 status를 resolved로 갱신 + Resolution 섹션 추가."""
    fm = question["fm"]
    body = question["body"]
    fm["status"] = "resolved"
    fm["resolved_at"] = datetime.now().date().isoformat()
    new_fm = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    addendum = f"\n\n## Auto Resolution\n\n```json\n{json.dumps(resolution, ensure_ascii=False, indent=2)}\n```\n"
    if "## Auto Resolution" not in body:
        body = body.rstrip() + addendum
    new_text = f"---\n{new_fm}\n---\n{body}\n"
    question["path"].write_text(new_text)


def main():
    apply = "--apply" in sys.argv
    category_filter = None
    for a in sys.argv[1:]:
        if a.startswith("--category="):
            category_filter = a.split("=", 1)[1]

    questions = load_questions(category_filter)
    print(f"[lint_resolver] open questions: {len(questions)}"
          f" {'(filter='+category_filter+')' if category_filter else ''}")

    slugs = vu.all_slugs()
    stats = {"fixed": 0, "stubbed": 0, "skipped": 0, "schema_fixed": 0, "errors": 0}
    cost_total = 0.0

    for q in questions:
        cat = q["fm"].get("category", "")
        target = ""
        # 'target: `xxx`' 형태 추출
        for r in q["fm"].get("related") or []:
            if isinstance(r, str):
                m = re.search(r"target:\s*`([^`]+)`", r)
                if m:
                    target = m.group(1)
                    break

        try:
            if cat == "broken_link" and target:
                verdict = llm_resolve_broken_link(target, slugs)
                action = verdict.get("action")
                if action == "fix":
                    new_slug = verdict.get("slug", "")
                    if new_slug in slugs:
                        if apply:
                            n = fix_wikilink_in_pages(target, new_slug)
                            mark_resolved(q, {**verdict, "fixes_applied": n})
                        stats["fixed"] += 1
                    else:
                        stats["skipped"] += 1
                elif action == "stub":
                    if apply:
                        if create_stub_page(target):
                            mark_resolved(q, {**verdict, "stub_created": target})
                            slugs.add(target)
                    stats["stubbed"] += 1
                else:
                    stats["skipped"] += 1
            elif cat == "schema_drift":
                if apply:
                    verdict = fix_schema_drift(q)
                    if verdict["action"] == "fix":
                        mark_resolved(q, verdict)
                        stats["schema_fixed"] += 1
                    else:
                        stats["skipped"] += 1
                else:
                    stats["schema_fixed"] += 1  # would-fix
            else:
                stats["skipped"] += 1
        except Exception as ex:
            stats["errors"] += 1
            print(f"  ! {q['path'].name}: {ex}")

    print(f"\n[lint_resolver] {'APPLY' if apply else 'DRY-RUN'} 결과:")
    print(f"  broken_link fix:   {stats['fixed']}")
    print(f"  broken_link stub:  {stats['stubbed']}")
    print(f"  schema_drift fix:  {stats['schema_fixed']}")
    print(f"  skipped:           {stats['skipped']}")
    print(f"  errors:            {stats['errors']}")
    if not apply:
        print(f"\n  적용하려면 --apply 추가")


if __name__ == "__main__":
    main()
