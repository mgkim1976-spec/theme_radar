"""theme_normalizer — raw theme 문자열을 canonical theme 사전으로 통합.

Korean 추출 결과의 themes[].name 필드는 보통 30-80자 서술문 (예: "거시: 미국 고용
부진→테이퍼링 늦춤 가능성 vs '연준은 진행'") — fuzzy 매칭이 거의 안 된다.

전략:
  1. 모든 채널 추출에서 themes[].name 수집 → 빈도 집계
  2. **LLM 태깅**: 각 verbose 이름을 gpt-5.4-nano가 1-3 단어 canonical 태그로 변환
     - 캐시: data/reference/theme_tags_cache.json (영구 보존, 증분만 LLM 호출)
     - 배치 50개씩 묶어 호출 (비용 ~$0.005/배치)
  3. 태그 위에서 RapidFuzz token_set_ratio ≥ 80 클러스터링
  4. 클러스터 대표(canonical) = 최빈 alias
  5. data/reference/theme_dictionary.json 저장 (증분 갱신)

옵션:
  --no-llm:       LLM 태깅 스킵 (raw 이름으로 fuzzy — 거의 클러스터 안 됨, 디버그용)
  --rebuild-tags: 캐시 무시하고 모든 이름 재태깅
  --rebuild:      dictionary 처음부터 재구축
"""
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from rapidfuzz import fuzz, process

sys.path.insert(0, str(Path(__file__).parent))
from config import CHANNELS, COMPILED, CACHE, channel_paths

from llm_client import chat_json, DEFAULT_MODEL

DICT_PATH = COMPILED / "theme_dictionary.json"
TAG_CACHE_PATH = CACHE / "theme_tags_cache.json"
SIMILARITY_THRESHOLD = 80
TAG_BATCH_SIZE = 50
LLM_MODEL = DEFAULT_MODEL


def slugify(s: str) -> str:
    s = unicodedata.normalize("NFC", s)
    s = re.sub(r"[^\w\s가-힣]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s[:80].lower() if s else "untitled"


def collect_raw_themes() -> list[dict]:
    """모든 채널 추출에서 (name, channel, upload_date) 수집."""
    rows = []
    for subdir in CHANNELS:
        ext_dir = channel_paths(subdir)["extractions"]
        if not ext_dir.exists():
            continue
        for f in sorted(ext_dir.glob("*_gpt-5.4-nano.json")):
            try:
                e = json.loads(f.read_text())
            except Exception:
                continue
            upload_date = f.name[:8]
            for t in e.get("themes", []):
                name = (t.get("name") or "").strip()
                if not name:
                    continue
                rows.append({"name": name, "channel": subdir, "upload_date": upload_date})
    return rows


# ============================================================
# LLM 태깅
# ============================================================
TAG_PROMPT = """당신은 한국어 투자 테마명을 1-3단어 표준 태그로 정규화합니다.

규칙:
- 1-3단어 (대부분 2단어)
- 핵심 명사·고유명사만, 동사·서술·콜론·따옴표 제거
- 동일 의미는 동일 태그 (예: "원전 정책 호재", "원전 부활", "원전_인프라" → 모두 "원전")
- 한국어, snake_case 또는 공백 가능
- 종목명 + 테마라면 종목 우선 (예: "테슬라 자율주행 재평가" → "테슬라_자율주행")
- 매크로/거시/정책 prefix는 의미 있을 때만 (예: "미국_고용", "한미_정상회담")

JSON으로만 응답:
{"tags": [{"i": 0, "tag": "..."}, {"i": 1, "tag": "..."}, ...]}

각 입력의 i 그대로 반환할 것."""


def llm_tag_batch(names: list[str]) -> tuple[list[str], dict]:
    """50개 묶음 → 50개 tag. 호출 비용 추적."""
    items = [{"i": i, "name": n[:200]} for i, n in enumerate(names)]
    user = json.dumps({"themes": items}, ensure_ascii=False)
    out, meta = chat_json(TAG_PROMPT, user, model=LLM_MODEL)
    tags_by_i = {item["i"]: item["tag"] for item in out.get("tags", [])}
    result = [tags_by_i.get(i, names[i][:30]) for i in range(len(names))]
    return result, {"in": meta.input_tokens, "out": meta.output_tokens, "cost": meta.cost_usd}


def normalize_tag(tag: str) -> str:
    """태그 표면 정규화 — 공백을 underscore로, 특수문자 제거."""
    if not tag:
        return ""
    tag = unicodedata.normalize("NFC", tag).strip()
    tag = tag.strip("\"'`")
    tag = re.sub(r"\s+", "_", tag)
    tag = re.sub(r"[^\w가-힣]", "", tag)
    return tag.lower()


def load_tag_cache() -> dict:
    if TAG_CACHE_PATH.exists():
        try:
            return json.loads(TAG_CACHE_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_tag_cache(cache: dict):
    CACHE.mkdir(parents=True, exist_ok=True)
    TAG_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2))


def tag_unique_names(unique_names: list[str], rebuild_tags: bool = False) -> dict[str, str]:
    """{verbose_name → canonical_tag} 반환. 캐시 우선, 미캐시만 LLM (또는 raw fallback)."""
    cache = {} if rebuild_tags else load_tag_cache()
    todo = [n for n in unique_names if n not in cache]
    if not todo:
        print(f"[theme_normalizer] tag cache hit 100% — {len(cache)} entries")
        return {n: cache[n] for n in unique_names if n in cache}

    if "OPENAI_API_KEY" not in os.environ:
        cached_count = len(unique_names) - len(todo)
        print(f"[theme_normalizer] OPENAI_API_KEY 미설정 — 캐시 {cached_count}개 활용, "
              f"미캐시 {len(todo)}개는 raw 이름 사용 (LLM 호출 없이는 클러스터링 효과 미약)")
        result = {}
        for n in unique_names:
            result[n] = cache.get(n, n)
        return result

    print(f"[theme_normalizer] LLM 태깅 — todo={len(todo)} / total={len(unique_names)} "
          f"(cache hit {len(unique_names) - len(todo)})")
    total_cost = 0.0
    n_ok = 0
    for batch_start in range(0, len(todo), TAG_BATCH_SIZE):
        batch = todo[batch_start:batch_start + TAG_BATCH_SIZE]
        try:
            tags, meta = llm_tag_batch(batch)
            total_cost += meta["cost"]
            for raw, tag in zip(batch, tags):
                cache[raw] = normalize_tag(tag) or raw[:30]
            n_ok += len(batch)
            if batch_start // TAG_BATCH_SIZE % 5 == 0:
                save_tag_cache(cache)  # 주기적 저장 (resilience)
                print(f"  ...{n_ok}/{len(todo)} done, cost=${round(total_cost, 4)}")
        except Exception as ex:
            print(f"  ! batch {batch_start} 실패: {ex}")
    save_tag_cache(cache)
    print(f"[theme_normalizer] LLM 태깅 완료 — total cost ${round(total_cost, 4)}")
    return {n: cache[n] for n in unique_names if n in cache}


# ============================================================
# 클러스터링
# ============================================================
def cluster_tags_fuzzy(tags: list[str]) -> dict[str, list[str]]:
    """token_set_ratio ≥ THRESHOLD 로 태그 클러스터.
    return: {canonical_tag: [member_tag, ...]} (member는 unique tag)"""
    clusters: dict[str, list[str]] = {}
    assigned: set[str] = set()
    for tag in tags:
        if tag in assigned:
            continue
        if clusters:
            best = process.extractOne(tag, list(clusters.keys()), scorer=fuzz.token_set_ratio)
            if best and best[1] >= SIMILARITY_THRESHOLD:
                clusters[best[0]].append(tag)
                assigned.add(tag)
                continue
        clusters[tag] = [tag]
        assigned.add(tag)
    return clusters


def build_dictionary(rows: list[dict], name_to_tag: dict[str, str], existing: dict | None = None) -> dict:
    """rows + name→tag 매핑 → canonical_themes 사전.

    canonical = 클러스터 내 가장 자주 등장하는 tag.
    aliases = 그 클러스터에 속한 모든 verbose name.
    """
    by_name: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_name[r["name"]].append(r)

    # tag → [verbose names]
    tag_to_names: dict[str, list[str]] = defaultdict(list)
    for name, tag in name_to_tag.items():
        if not tag:
            continue
        tag_to_names[tag].append(name)

    unique_tags = sorted(tag_to_names.keys(), key=lambda t: -sum(len(by_name[n]) for n in tag_to_names[t]))
    clusters = cluster_tags_fuzzy(unique_tags)

    # 기존 카논과 alias 보존 (기존 사전이 있다면)
    existing_canon: dict[str, set[str]] = {}
    if existing and "canonical_themes" in existing:
        for canon, info in existing["canonical_themes"].items():
            existing_canon[canon] = set(info.get("aliases", []))

    canonical_themes: dict[str, dict] = {}
    for cluster_head, member_tags in clusters.items():
        # 모든 verbose alias 수집
        aliases: list[str] = []
        for tag in member_tags:
            aliases.extend(tag_to_names.get(tag, []))
        if not aliases:
            continue
        # 카논 = 빈도 최고 verbose alias의 tag
        alias_freq = sorted(aliases, key=lambda a: -len(by_name.get(a, [])))
        top_alias = alias_freq[0]
        top_tag = name_to_tag.get(top_alias, cluster_head)
        canon = top_tag or cluster_head

        all_rows: list[dict] = []
        for a in aliases:
            all_rows.extend(by_name.get(a, []))
        if len(all_rows) < 1:
            continue
        dates = sorted(r["upload_date"] for r in all_rows)
        channels = sorted({r["channel"] for r in all_rows})
        canonical_themes[canon] = {
            "slug": slugify(canon),
            "tag_members": sorted(set(member_tags)),
            "aliases": sorted(set(aliases)),
            "first_seen": dates[0] if dates else None,
            "last_seen": dates[-1] if dates else None,
            "total_mentions": len(all_rows),
            "channels": channels,
        }

    return {
        "version": 2,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "tagging_model": LLM_MODEL,
        "canonical_themes": canonical_themes,
    }


def main():
    use_llm = "--no-llm" not in sys.argv
    rebuild_tags = "--rebuild-tags" in sys.argv
    rebuild = "--rebuild" in sys.argv

    COMPILED.mkdir(parents=True, exist_ok=True)
    existing = None
    if DICT_PATH.exists() and not rebuild:
        try:
            existing = json.loads(DICT_PATH.read_text())
        except Exception:
            existing = None

    rows = collect_raw_themes()
    print(f"[theme_normalizer] collected {len(rows)} theme mentions "
          f"across {len({r['channel'] for r in rows})} channels")
    if not rows:
        print("[theme_normalizer] no extractions found — exit")
        return

    unique_names = sorted({r["name"] for r in rows})
    print(f"[theme_normalizer] unique verbose names: {len(unique_names)}")

    if use_llm:
        name_to_tag = tag_unique_names(unique_names, rebuild_tags=rebuild_tags)
    else:
        print("[theme_normalizer] --no-llm: raw 이름으로 fuzzy (클러스터링 효과 미약)")
        name_to_tag = {n: n for n in unique_names}

    out = build_dictionary(rows, name_to_tag, existing=existing)
    DICT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2))

    n = len(out["canonical_themes"])
    multi = sum(1 for v in out["canonical_themes"].values() if v["total_mentions"] >= 2)
    print(f"[theme_normalizer] {n} canonical themes "
          f"(multi-mention ≥2: {multi}) → {DICT_PATH}")


if __name__ == "__main__":
    main()
