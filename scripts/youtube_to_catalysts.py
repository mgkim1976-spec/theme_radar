"""Convert YouTube extraction policy/diplomatic mentions → catalysts.yaml format.

Reads from data/youtube/<channel>/extractions_v2/*.json
Outputs to geopolitical_investor/data/catalysts_from_youtube.yaml (review before merge).

Aggregation:
- Same event_type + similar timing = same catalyst (deduplicated)
- Multiple mentions tracked as `mentioned_by` array
- Average conviction across mentions
"""
import json
import re
from collections import defaultdict
import sys
from datetime import datetime, date, timedelta
from pathlib import Path
import yaml

sys.path.insert(0, str(Path(__file__).parent))
from config import YOUTUBE_DATA, CATALYSTS_YAML, CHANNELS as ALL_CHANNELS

YOUTUBE_BASE = YOUTUBE_DATA
OUT_FILE = CATALYSTS_YAML.parent / "catalysts_from_youtube.yaml"
EXISTING_FILE = CATALYSTS_YAML

# 모든 채널 (확장 시 config.py에서 자동 반영)
CHANNELS = list(ALL_CHANNELS.keys())

# Map our event_type → catalysts.yaml category
EVENT_TYPE_TO_CATEGORY = {
    "한미정상회담": "summit",
    "한중정상회담": "summit",
    "한일정상회담": "summit",
    "한미일정상회담": "summit",
    "G7": "summit",
    "G20": "summit",
    "APEC": "summit",
    "UN총회": "summit",
    "한미경제대화": "treaty",
    "한미통상장관회담": "treaty",
    "한중외교장관회담": "treaty",
    "美대통령선거": "election",
    "한국선거": "election",
    "FOMC": "policy_meeting",
    "한은_금통위": "policy_meeting",
    "ECB": "policy_meeting",
    "BOJ": "policy_meeting",
    "美CHIPS법": "legal",
    "美IRA": "legal",
    "EU_CRMA": "legal",
    "K_칩스법": "legal",
    "어닝시즌": "earnings",  # 새 카테고리 (기존 catalysts.yaml에 없음 — 별도 표시)
    "기타": "other",
}

# Map our event_type → ISO actor codes
EVENT_TYPE_TO_ACTORS = {
    "한미정상회담": ["KR", "US"],
    "한중정상회담": ["KR", "CN"],
    "한일정상회담": ["KR", "JP"],
    "한미일정상회담": ["KR", "US", "JP"],
    "G7": ["US", "UK", "FR", "DE", "IT", "JP", "CA", "EU"],
    "G20": ["G20"],
    "APEC": ["APEC"],
    "UN총회": ["UN"],
    "한미경제대화": ["KR", "US"],
    "한미통상장관회담": ["KR", "US"],
    "한중외교장관회담": ["KR", "CN"],
    "美대통령선거": ["US"],
    "한국선거": ["KR"],
    "FOMC": ["US", "FED"],
    "한은_금통위": ["KR", "BOK"],
    "ECB": ["EU", "ECB"],
    "BOJ": ["JP", "BOJ"],
    "美CHIPS법": ["US"],
    "美IRA": ["US"],
    "EU_CRMA": ["EU"],
    "K_칩스법": ["KR"],
}

# Sector keyword → representative KRX tickers
SECTOR_TO_TICKERS = {
    "방산": ["LIG넥스원", "한화에어로스페이스", "현대로템", "한국항공우주"],
    "원전": ["두산에너빌리티", "한전기술", "한전KPS", "대우건설"],
    "전력설비": ["LS일렉트릭", "HD현대일렉트릭", "효성중공업", "대한전선"],
    "2차전지": ["LG에너지솔루션", "삼성SDI", "POSCO퓨처엠", "에코프로비엠"],
    "배터리": ["LG에너지솔루션", "삼성SDI", "POSCO퓨처엠"],
    "반도체": ["삼성전자", "SK하이닉스", "원익IPS", "한미반도체"],
    "메모리": ["삼성전자", "SK하이닉스", "마이크론"],
    "조선": ["HD현대중공업", "한화오션", "삼성중공업"],
    "자동차": ["현대차", "기아", "현대모비스"],
    "바이오": ["삼성바이오로직스", "셀트리온", "알테오젠"],
    "원유": ["S-Oil", "GS", "SK이노베이션"],
    "LNG": ["한국가스공사", "HD현대중공업"],
    "건설": ["현대건설", "대우건설", "삼성물산"],
    "재건": ["현대건설", "두산에너빌리티", "한국전력기술"],
    "면세": ["호텔신라", "현대백화점"],
    "여행": ["대한항공", "하나투어"],
    "엔터": ["하이브", "JYP Ent.", "SM"],
    "철강": ["POSCO홀딩스", "현대제철"],
    "화장품": ["아모레퍼시픽", "LG생활건강"],
}

def slug_event_type(et: str) -> str:
    """한미정상회담 → kor_us_summit"""
    mapping = {
        "한미정상회담": "kor_us_summit",
        "한중정상회담": "kor_cn_summit",
        "한일정상회담": "kor_jp_summit",
        "한미일정상회담": "kor_us_jp_summit",
        "한미경제대화": "kor_us_econ_dialogue",
        "한미통상장관회담": "kor_us_trade_min",
        "한중외교장관회담": "kor_cn_foreign_min",
        "한국선거": "kor_election",
        "美대통령선거": "us_election",
        "한은_금통위": "bok_meeting",
        "美CHIPS법": "us_chips_act",
        "美IRA": "us_ira",
        "EU_CRMA": "eu_crma",
        "K_칩스법": "kor_chips_act",
        "어닝시즌": "earnings_season",
    }
    return mapping.get(et, et.lower().replace(" ", "_"))


def estimate_date(timing: str, video_date_str: str) -> tuple[date, bool]:
    """timing label → estimated catalyst date (date, is_approx)."""
    try:
        vid_date = datetime.strptime(video_date_str, "%Y%m%d").date()
    except Exception:
        vid_date = date.today()

    if timing == "임박_1개월내":
        return vid_date + timedelta(days=15), True
    if timing == "예정_1-3개월":
        return vid_date + timedelta(days=60), True
    if timing == "예정_3개월이상":
        return vid_date + timedelta(days=120), True
    if timing == "진행중":
        return vid_date, True
    if timing == "과거":
        return vid_date - timedelta(days=15), True
    return vid_date + timedelta(days=30), True


def collect_mentions():
    """Read all extractions, return list of mention dicts."""
    mentions = []
    for ch in CHANNELS:
        ext_dir = YOUTUBE_BASE / ch / "extractions_v2"
        if not ext_dir.exists():
            continue
        for f in sorted(ext_dir.glob("*_gpt-5.4-nano.json")):
            video_date = f.name[:8]
            video_id = f.name[9:].split("_gpt")[0]
            try:
                e = json.loads(f.read_text())
            except Exception:
                continue
            for p in e.get("policy_diplomatic_mentions", []):
                if p.get("event_type") in ("기타",):
                    continue
                # Only forward-looking events (skip pure 과거)
                if p.get("timing") == "과거":
                    continue
                est_date, is_approx = estimate_date(p.get("timing", ""), video_date)
                # Skip events too far in past from today
                if est_date < date.today() - timedelta(days=30):
                    continue
                mentions.append({
                    "channel": ch,
                    "video_date": video_date,
                    "video_id": video_id,
                    "event_type": p["event_type"],
                    "event_label": p.get("event_label", ""),
                    "timing": p.get("timing", ""),
                    "stance": p.get("stance", "중립"),
                    "sectors": p.get("expected_impact_sectors", []),
                    "estimated_date": est_date,
                    "is_approx": is_approx,
                })
    return mentions


def aggregate(mentions):
    """Group by (event_type, year-month of estimated date)."""
    groups = defaultdict(list)
    for m in mentions:
        key = (m["event_type"], m["estimated_date"].strftime("%Y-%m"))
        groups[key].append(m)
    return groups


def sectors_to_assets(sectors):
    """Map sector keywords → unique KRX tickers list."""
    tickers = []
    seen = set()
    for sec in sectors:
        for keyword, tks in SECTOR_TO_TICKERS.items():
            if keyword in sec:
                for tk in tks:
                    if tk not in seen:
                        tickers.append(tk)
                        seen.add(tk)
                break
    return tickers


def to_catalyst_yaml(group_key, mentions):
    """Convert one aggregated group → catalyst yaml entry."""
    event_type, ym = group_key
    sample = mentions[0]
    est_date = sample["estimated_date"]

    # Aggregate sectors
    all_sectors = []
    for m in mentions:
        for s in m["sectors"]:
            if s not in all_sectors:
                all_sectors.append(s)

    affected = sectors_to_assets(all_sectors)
    actors = EVENT_TYPE_TO_ACTORS.get(event_type, [])
    category = EVENT_TYPE_TO_CATEGORY.get(event_type, "other")

    # Aggregate stances
    stance_counter = defaultdict(int)
    for m in mentions:
        stance_counter[m["stance"]] += 1
    dominant_stance = max(stance_counter, key=stance_counter.get)

    # Sources: list of channel:date
    sources = sorted({f"{m['channel']}:{m['video_date']}" for m in mentions})

    title_parts = [event_type, ym]
    if all_sectors:
        title_parts.append("/".join(all_sectors[:3]))
    title = " — ".join(title_parts)

    return {
        "id": f"{slug_event_type(event_type)}_{ym.replace('-', '_')}",
        "date": est_date.isoformat(),
        "date_approx": sample["is_approx"],
        "category": category,
        "actors": actors,
        "title": title,
        "affected_assets": affected,
        "tags": [event_type] + all_sectors[:5],
        "base_question": f"How will the {event_type} affect {'/'.join(all_sectors[:2]) or 'Korean equities'}?",
        # Extension fields (catalysts_from_youtube.yaml only)
        "_youtube": {
            "mentions": len(mentions),
            "sources": sources,
            "dominant_stance": dominant_stance,
            "stance_breakdown": dict(stance_counter),
            "raw_sectors": all_sectors,
            "sample_label": sample["event_label"],
        },
    }


def main():
    mentions = collect_mentions()
    groups = aggregate(mentions)
    catalysts = []
    for key, ms in sorted(groups.items(), key=lambda x: (x[1][0]["estimated_date"], x[0][0])):
        catalysts.append(to_catalyst_yaml(key, ms))

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# Auto-generated from YouTube extractions (한균수 + 86번가)\n"
        f"# Generated: {datetime.now().isoformat()}\n"
        f"# Source mentions: {len(mentions)} from {len(set(m['channel'] for m in mentions))} channels\n"
        "# Review before merging into catalysts.yaml\n"
        "# Strip _youtube field before merge (it's metadata)\n"
        "\n"
    )
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(catalysts, f, allow_unicode=True, sort_keys=False, default_flow_style=False)

    # Summary
    print(f"Source mentions: {len(mentions)}")
    print(f"Aggregated catalysts: {len(catalysts)}")
    print(f"Output: {OUT_FILE}")
    print()
    print("=== Summary by category ===")
    by_cat = defaultdict(int)
    for c in catalysts:
        by_cat[c["category"]] += 1
    for cat, cnt in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {cat:20} {cnt}")
    print()
    print("=== Top 10 catalysts (by mention count) ===")
    catalysts_sorted = sorted(catalysts, key=lambda c: -c["_youtube"]["mentions"])
    for c in catalysts_sorted[:10]:
        print(f"  [{c['date']}] {c['id']:40} mentions={c['_youtube']['mentions']:2} "
              f"stance={c['_youtube']['dominant_stance']:4} assets={len(c['affected_assets']):2}")


if __name__ == "__main__":
    main()
