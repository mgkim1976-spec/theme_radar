"""query — 사용자 질문을 vault 기반으로 답변, decisions/{slug}.md 저장.

Karpathy LLM Wiki 패턴의 핵심 piece. 2-stage LLM:
  Stage 1 (Router) — 질문 + vault 인덱스 → 관련 슬러그 5-10개
  Stage 2 (Synth)  — 질문 + 라우팅 페이지 풀텍스트 → 답변 + 출처

비용: 회당 ~$0.005 (router + synth 합)
저장: VAULT/decisions/{YYYYMMDD}_{질문slug}.md

사용:
  python3 query.py "한균수와 86번가 중 누가 원전 테마를 더 강하게 봤어?"
  python3 query.py --top=15 "..."        # 라우팅 페이지 수 (기본 8)
  python3 query.py --no-save "..."       # decisions/ 저장 안 함
"""
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import vault_utils as vu
from config import VAULT
from llm_client import chat as llm_chat, chat_json, DEFAULT_MODEL

DECISIONS_DIR = VAULT / "decisions"
DEFAULT_TOP_K = 8
MAX_PAGES_TO_INDEX = 600  # router에 전달할 최대 페이지 수
MAX_PAGE_BODY_CHARS = 6000  # synth에 페이지당 truncate


ROUTER_SYSTEM = (
    "당신은 한국 투자 메소돌로지 wiki의 라우터입니다. "
    "사용자 질문에 답하기 위해 어떤 vault 페이지가 필요한지 슬러그 배열로 답하세요."
)

SYNTH_SYSTEM = (
    "당신은 한국 투자 메소돌로지 분석가입니다. 주어진 vault 페이지들을 근거로 "
    "사용자 질문에 답하세요. 인용은 [[slug]] 형식. 페이지에 없는 정보는 "
    "'(vault 데이터 없음)' 으로 명시. 답변은 한국어 마크다운, 2-5 문단."
)


def slugify_question(q: str, max_len: int = 50) -> str:
    s = unicodedata.normalize("NFC", q)
    s = re.sub(r"[^\w\s가-힣]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:max_len].lower() or "query"


def build_router_prompt(question: str, index: dict) -> str:
    """페이지 메타만 포함된 가벼운 인덱스를 LLM에 전달."""
    items = []
    for slug, meta in index.items():
        # 시스템·템플릿 제외
        if slug in vu.SYSTEM_PAGES or slug.startswith("_"):
            continue
        items.append({
            "slug": slug,
            "type": meta.get("type"),
            "title": meta.get("title", "")[:60],
            "tags": (meta.get("tags") or [])[:5],
            "lifecycle": meta.get("lifecycle"),
        })
    items = items[:MAX_PAGES_TO_INDEX]
    return f"""# 사용자 질문
{question}

# Vault 페이지 인덱스 ({len(items)}개)
```json
{json.dumps(items, ensure_ascii=False)}
```

# 작업
이 질문에 답하기 위해 가장 관련 있는 페이지 슬러그를 5-10개 골라 JSON으로 응답하세요.
페이지 type은 다양 (theme, methodology, youtuber, catalyst, regime, decision 등).
질문이 비교성이면 비교 대상 모두 포함. 채널 메소돌로지 비교는 youtubers/ + methodologies/ 함께.

응답 형식 (JSON만, 다른 텍스트 금지):
{{"slugs": ["...", "..."], "reasoning": "왜 이 페이지들을 골랐는지 한 문장"}}"""


def route(question: str, index: dict, top_k: int) -> tuple[list[str], str, dict]:
    prompt = build_router_prompt(question, index)
    data, r = chat_json(ROUTER_SYSTEM, prompt, model=DEFAULT_MODEL)
    slugs = data.get("slugs") or []
    # 인덱스에 실제로 존재하는 슬러그만 keep
    valid = [s for s in slugs if s in index][:top_k]
    reasoning = data.get("reasoning", "")
    return valid, reasoning, r.as_meta()


def build_synth_prompt(question: str, pages: list[vu.Page]) -> str:
    page_blocks = []
    for p in pages:
        body = p.body[:MAX_PAGE_BODY_CHARS]
        page_blocks.append(f"## [[{p.slug}]] (type={p.type})\n\n{body}\n")
    pages_text = "\n---\n\n".join(page_blocks)
    return f"""# 사용자 질문
{question}

# 참조 페이지 ({len(pages)}개)
{pages_text}

# 작업
위 페이지들을 근거로 질문에 답하세요. 답변 구조:
1. **요약** — 1-2 문단의 직접 답
2. **근거** — bullet로 각 인용에 [[slug]] 명시
3. **남은 의문** — 답이 부분적이면 추가 데이터 필요한 부분 (선택)

페이지에 없는 정보는 추측 금지. '(vault에 없음)' 명시."""


def synthesize(question: str, pages: list[vu.Page]) -> tuple[str, dict]:
    prompt = build_synth_prompt(question, pages)
    r = llm_chat(SYNTH_SYSTEM, prompt, model=DEFAULT_MODEL)
    return r.text, r.as_meta()


def save_decision(question: str, answer: str, sources: list[str],
                  router_meta: dict, synth_meta: dict, reasoning: str) -> Path:
    DECISIONS_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().date().isoformat()
    slug_part = slugify_question(question)
    fname = f"{today}_{slug_part}.md"
    path = DECISIONS_DIR / fname
    src_block = "\n".join(f"  - {s}" for s in sources)
    total_cost = router_meta["cost_usd"] + synth_meta["cost_usd"]
    body = f"""---
type: decision
question: {json.dumps(question, ensure_ascii=False)}
asked_at: {today}
sources:
{src_block}
status: answered
tags: [decision, query-result]
---

# Q: {question}

{answer.strip()}

---

## Meta

- **라우터 추론**: {reasoning}
- **참조 페이지**: {len(sources)}개
- **LLM**: {DEFAULT_MODEL} · 비용 ${total_cost:.5f} (router ${router_meta['cost_usd']:.5f} + synth ${synth_meta['cost_usd']:.5f})
- **참조 출처**:
{chr(10).join(f'  - [[{s}]]' for s in sources)}
"""
    path.write_text(body)
    return path


def main():
    args = list(sys.argv[1:])
    no_save = "--no-save" in args
    args = [a for a in args if a != "--no-save"]
    top_k = DEFAULT_TOP_K
    cleaned = []
    for a in args:
        if a.startswith("--top="):
            top_k = int(a.split("=", 1)[1])
        else:
            cleaned.append(a)
    if not cleaned:
        print("Usage: python3 query.py [--top=N] [--no-save] \"질문\"", file=sys.stderr)
        sys.exit(1)
    question = " ".join(cleaned)

    print(f"[query] Q: {question}\n")

    # 1. 인덱스 빌드 (증분 가능하지만 MVP는 매번 새로)
    index = vu.build_index()
    print(f"[query] Vault 인덱스: {len(index)} 페이지")

    # 2. 라우터
    print(f"[query] Router → 관련 페이지 추출 중...")
    slugs, reasoning, rmeta = route(question, index, top_k)
    if not slugs:
        print("[query] ❌ 관련 페이지 0개 — 질문을 더 구체적으로")
        return
    print(f"[query] Router 결과 ({len(slugs)}): {slugs}")
    print(f"[query] Reasoning: {reasoning}\n")

    # 3. 페이지 로드
    pages = []
    page_map = {p.slug: p for p in vu.iter_pages()}
    for s in slugs:
        if s in page_map:
            pages.append(page_map[s])
    if not pages:
        print("[query] ❌ 라우팅된 페이지 로드 실패")
        return

    # 4. 합성
    print(f"[query] Synthesizer → 답변 생성 중...")
    answer, smeta = synthesize(question, pages)

    print("\n" + "=" * 60)
    print(answer)
    print("=" * 60)
    total_cost = rmeta["cost_usd"] + smeta["cost_usd"]
    print(f"\n[query] 총 비용: ${total_cost:.5f}")
    print(f"  router: ${rmeta['cost_usd']:.5f} (in={rmeta['input_tokens']}, out={rmeta['output_tokens']})")
    print(f"  synth:  ${smeta['cost_usd']:.5f} (in={smeta['input_tokens']}, out={smeta['output_tokens']})")

    # 5. decisions/ 저장 + Loop B (자동 backlink + citation_index)
    if not no_save:
        path = save_decision(question, answer, slugs, rmeta, smeta, reasoning)
        rel = path.relative_to(VAULT)
        print(f"\n[query] 저장: [[{rel.with_suffix('')}]]")
        try:
            from decision_indexer import index_decision, load_citation_index, update_citation_counts, save_citation_index
            decision_slug = str(rel.with_suffix(""))
            r = index_decision(decision_slug, slugs)
            idx = update_citation_counts(slugs)
            save_citation_index(idx)
            print(f"[query] backlink: +{len(r['added'])} pages, "
                  f"missing {len(r['missing'])}, citation_index 갱신")
        except Exception as ex:
            print(f"[query] decision_indexer 실패 (무시): {ex}")


if __name__ == "__main__":
    main()
