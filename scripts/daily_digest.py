"""daily_digest — 매일 아침 한 페이지로 요약된 'Today' 페이지.

theme_dashboard가 dashboard_signals.json을 만들어두면 이 모듈이:
  1. 어제 daily/{yesterday}.md frontmatter와 비교 → delta (오늘 NEW만)
  2. 채널 best/worst, 현재 regime, citation top 같은 단일 metric 함께 표시
  3. VAULT/today.md 항상 덮어쓰기 + VAULT/daily/{YYYY-MM-DD}.md 아카이브

사용:
  python3 daily_digest.py            # 매일 자동 (기본)
  python3 daily_digest.py --llm-summary  # LLM 1줄 요약 추가 (~$0.001)

사람이 매일 아침 today.md 한 페이지만 열면 충분하도록 설계.
"""
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import VAULT, COMPILED

TODAY = date.today()
DASH_JSON_PATH = COMPILED / "dashboard_signals.json"
WEIGHTS_PATH = COMPILED / "channel_weights.json"
SCORECARD_PATH = COMPILED / "scorecard.json"
REGIME_PATH = COMPILED / "regime_alignment.json"
CITATION_PATH = COMPILED / "citation_index.json"

TODAY_PAGE = VAULT / "today.md"
DAILY_DIR = VAULT / "daily"


# ============================================================
# 어제 디지스트 로드 (delta 계산용)
# ============================================================
def yesterday_path() -> Path:
    yp = DAILY_DIR / f"{(TODAY - timedelta(days=1)).isoformat()}.md"
    if yp.exists():
        return yp
    # 더 거슬러 — 휴일 등으로 어제 안 돌았을 수 있음
    for back in range(2, 8):
        p = DAILY_DIR / f"{(TODAY - timedelta(days=back)).isoformat()}.md"
        if p.exists():
            return p
    return None


def parse_archived_signals(path: Path) -> dict:
    """archive 페이지의 frontmatter에서 신호 set 복원."""
    if not path or not path.exists():
        return {"emerging": set(), "accelerating": set(), "consensus": {}, "fading": set()}
    text = path.read_text()
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {"emerging": set(), "accelerating": set(), "consensus": {}, "fading": set()}
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except Exception:
        return {"emerging": set(), "accelerating": set(), "consensus": {}, "fading": set()}
    return {
        "emerging": set(fm.get("emerging") or []),
        "accelerating": set(fm.get("accelerating") or []),
        # consensus는 채널 수 비교 위해 dict
        "consensus": {c["canonical"]: c.get("n_channels", 0) for c in fm.get("consensus") or []},
        "fading": set(fm.get("fading") or []),
    }


# ============================================================
# 오늘 신호 + delta 계산
# ============================================================
def load_today_signals() -> dict:
    if not DASH_JSON_PATH.exists():
        return {"emerging": [], "accelerating": [], "consensus": [], "fading": []}
    return json.loads(DASH_JSON_PATH.read_text()).get("signals", {})


def compute_deltas(today_sig: dict, prev: dict) -> dict:
    """오늘만의 NEW 항목 계산."""
    today_emerging = {x["canonical"] for x in today_sig["emerging"]}
    today_accel = {x["canonical"] for x in today_sig["accelerating"]}
    today_fading = {x["canonical"] for x in today_sig["fading"]}
    today_consensus_n = {x["canonical"]: len(x.get("channels_14d") or []) for x in today_sig["consensus"]}

    return {
        "new_emerging": today_emerging - prev["emerging"],
        "new_accel": today_accel - prev["accelerating"],
        "new_fading": today_fading - prev["fading"],
        "consensus_strengthened": [
            (c, prev["consensus"].get(c, 0), n) for c, n in today_consensus_n.items()
            if n > prev["consensus"].get(c, 0)
        ],
    }


# ============================================================
# 보조 데이터 로드
# ============================================================
def load_weights() -> dict:
    if WEIGHTS_PATH.exists():
        try:
            return json.loads(WEIGHTS_PATH.read_text()).get("channels", {})
        except Exception:
            pass
    return {}


def load_scorecard() -> dict:
    if SCORECARD_PATH.exists():
        try:
            return json.loads(SCORECARD_PATH.read_text())
        except Exception:
            pass
    return {}


def load_regime() -> dict:
    if REGIME_PATH.exists():
        try:
            return json.loads(REGIME_PATH.read_text())
        except Exception:
            pass
    return {}


def load_top_citations(n: int = 5) -> list:
    if not CITATION_PATH.exists():
        return []
    try:
        d = json.loads(CITATION_PATH.read_text())
        counts = d.get("counts") or {}
        return sorted(counts.items(), key=lambda x: -x[1])[:n]
    except Exception:
        return []


# ============================================================
# 렌더링
# ============================================================
def render_today(today_sig: dict, deltas: dict, weights: dict, scorecard: dict,
                 regime: dict, citations: list, llm_summary: str = "") -> str:
    # 채널 best/worst
    best_ch, worst_ch = None, None
    if scorecard.get("by_channel"):
        ch_data = []
        for ch, entry in scorecard["by_channel"].items():
            e = (entry or {}).get("90d") or (entry or {}).get("30d")
            if e:
                ch_data.append((ch, e.get("mean", 0), e.get("win_rate", 0), e.get("n", 0)))
        if ch_data:
            ch_data.sort(key=lambda x: -x[1])
            best_ch = ch_data[0]
            worst_ch = ch_data[-1] if len(ch_data) > 1 else None

    # 단계별 핵심
    n_emerging = len(today_sig.get("emerging", []))
    n_accel = len(today_sig.get("accelerating", []))
    n_consensus = len(today_sig.get("consensus", []))
    n_fading = len(today_sig.get("fading", []))

    # frontmatter용 미리 빌드 (f-string 안에 list comprehension 충돌 회피)
    fm_emerging = json.dumps(sorted(deltas["new_emerging"]), ensure_ascii=False)
    fm_accel = json.dumps(sorted(deltas["new_accel"]), ensure_ascii=False)
    fm_consensus = json.dumps(
        [{"canonical": canon, "n_channels": n_now} for canon, _, n_now in deltas["consensus_strengthened"][:50]],
        ensure_ascii=False,
    )
    fm_fading = json.dumps(sorted(deltas["new_fading"]), ensure_ascii=False)
    today_label = TODAY.strftime("%Y-%m-%d (%a)")

    out = []
    out.append(f"""---
type: digest
date: {TODAY.isoformat()}
generated_at: {datetime.now().isoformat(timespec="seconds")}
emerging: {fm_emerging}
accelerating: {fm_accel}
consensus: {fm_consensus}
fading: {fm_fading}
tags: [digest, today, auto]
---

# 📅 Today — {today_label}
""")

    if llm_summary:
        out.append(f"\n> {llm_summary}\n")

    # 매크로 환경 한 줄
    cur_regime = (regime or {}).get("current_regime", "?")
    score = (regime or {}).get("regime_score", "?")
    conf = (regime or {}).get("regime_confidence", "?")
    out.append(f"\n## 📊 환경\n")
    out.append(f"- **Regime**: `{cur_regime}` (score={score}, conf={conf})")
    if best_ch:
        out.append(f"- **Best 채널**: `{best_ch[0]}` 90d/30d {best_ch[1]*100:+.1f}% · win {best_ch[2]:.0%} · weight {weights.get(best_ch[0], {}).get('weight', '?')}")
    if worst_ch and worst_ch != best_ch:
        out.append(f"- **Worst 채널**: `{worst_ch[0]}` {worst_ch[1]*100:+.1f}% · win {worst_ch[2]:.0%}")

    # 오늘 NEW (delta)
    out.append(f"\n## 🆕 오늘 새로 등장 ({len(deltas['new_emerging'])}개 NEW · 누적 {n_emerging})\n")
    if not deltas["new_emerging"]:
        out.append("_(어제 대비 신규 없음)_")
    else:
        # 오늘 신호 중 new에 해당하는 것만 상세
        em_map = {x["canonical"]: x for x in today_sig["emerging"]}
        for canon in sorted(deltas["new_emerging"]):
            x = em_map.get(canon, {})
            slug = x.get("slug", canon)
            first = x.get("first", "?")
            n7 = x.get("n7", "?")
            out.append(f"- [[themes/{slug}|{canon}]] · 첫 언급 `{first}` · 7일 {n7}회")

    # 오늘 가속 (drop in)
    out.append(f"\n## 🚀 오늘 가속 진입 ({len(deltas['new_accel'])}개 NEW · 누적 {n_accel})\n")
    if not deltas["new_accel"]:
        out.append("_(없음)_")
    else:
        ac_map = {x["canonical"]: x for x in today_sig["accelerating"]}
        for canon in sorted(deltas["new_accel"]):
            x = ac_map.get(canon, {})
            slug = x.get("slug", canon)
            ratio = x.get("ratio", "?")
            n7 = x.get("n7", "?")
            n30 = x.get("n30", "?")
            out.append(f"- [[themes/{slug}|{canon}]] · 7d/이전30d 비율 **{ratio}** ({n7}/{n30-n7 if isinstance(n30,int) and isinstance(n7,int) else '?'})")

    # 합의 강화
    out.append(f"\n## 🤝 합의 강화 ({len(deltas['consensus_strengthened'])}개 변화 · 누적 {n_consensus})\n")
    if not deltas["consensus_strengthened"]:
        out.append("_(채널 수 변화 없음)_")
    else:
        cons_map = {x["canonical"]: x for x in today_sig["consensus"]}
        for canon, prev_n, now_n in sorted(deltas["consensus_strengthened"], key=lambda x: -(x[2] - x[1])):
            x = cons_map.get(canon, {})
            slug = x.get("slug", canon)
            chs = x.get("channels_14d") or []
            out.append(f"- [[themes/{slug}|{canon}]] · {prev_n} → **{now_n}채널** ({', '.join(chs)})")

    # 새 fading
    out.append(f"\n## 📉 새로 Fading 진입 ({len(deltas['new_fading'])}개 NEW · 누적 {n_fading})\n")
    if not deltas["new_fading"]:
        out.append("_(없음)_")
    else:
        fa_map = {x["canonical"]: x for x in today_sig["fading"]}
        for canon in list(sorted(deltas["new_fading"]))[:15]:
            x = fa_map.get(canon, {})
            slug = x.get("slug", canon)
            last = x.get("last", "?")
            n_total = x.get("n_total", "?")
            out.append(f"- [[themes/{slug}|{canon}]] · 마지막 `{last}` · 누적 {n_total}회")

    # 우선 읽기
    out.append(f"\n## 🎯 우선 읽기\n")
    if citations:
        out.append("**자주 인용되는 페이지** (decisions에 자주 등장):")
        for slug, n in citations:
            out.append(f"- [[{slug}]] · {n}회 인용")
    else:
        out.append("_(아직 decision 인용 데이터 없음)_")

    out.append(f"\n---\n\n→ 상세: [[themes/_dashboard]] · [[validation/scorecard]]")
    out.append(f"→ 어제 디지스트: [[daily/{(TODAY - timedelta(days=1)).isoformat()}]]")

    return "\n".join(out)


def main():
    use_llm = "--llm-summary" in sys.argv

    today_sig = load_today_signals()
    if not today_sig.get("emerging") and not today_sig.get("consensus"):
        print("[daily_digest] dashboard_signals.json 비어있음 — theme_dashboard 먼저 실행")
        return

    yp = yesterday_path()
    prev = parse_archived_signals(yp)
    deltas = compute_deltas(today_sig, prev)

    weights = load_weights()
    scorecard = load_scorecard()
    regime = load_regime()
    citations = load_top_citations()

    llm_summary = ""
    if use_llm:
        try:
            from llm_client import chat
            ctx = (
                f"오늘 NEW emerging={len(deltas['new_emerging'])}, "
                f"가속 진입={len(deltas['new_accel'])}, "
                f"합의 강화={len(deltas['consensus_strengthened'])}, "
                f"새 fading={len(deltas['new_fading'])}. "
                f"현재 regime: {regime.get('current_regime','?')}. "
                f"NEW emerging 5개 샘플: {list(deltas['new_emerging'])[:5]}. "
            )
            r = chat(
                "당신은 한국 투자 지식베이스의 시장 요약가입니다.",
                f"오늘 시장 동향을 1-2 문장으로 요약하세요. 데이터:\n{ctx}",
                model="gpt-5.4-nano",
            )
            llm_summary = r.text.strip().replace("\n", " ")
        except Exception as ex:
            llm_summary = f"_(LLM 요약 실패: {ex})_"

    rendered = render_today(today_sig, deltas, weights, scorecard, regime, citations, llm_summary)

    TODAY_PAGE.write_text(rendered)
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = DAILY_DIR / f"{TODAY.isoformat()}.md"
    archive_path.write_text(rendered)

    print(f"[daily_digest] today.md 갱신 + daily/{TODAY.isoformat()}.md 아카이브")
    print(f"  NEW: emerging={len(deltas['new_emerging'])} accel={len(deltas['new_accel'])} "
          f"consensus_+={len(deltas['consensus_strengthened'])} fading={len(deltas['new_fading'])}")


if __name__ == "__main__":
    main()
