"""Build KRX (KOSPI+KOSDAQ) ticker whitelist with name aliases for fuzzy matching."""
import json
import re
from pathlib import Path
import FinanceDataReader as fdr

import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from config import KRX_TICKERS
OUT = KRX_TICKERS
OUT.parent.mkdir(parents=True, exist_ok=True)

records = []
for market in ["KOSPI", "KOSDAQ"]:
    df = fdr.StockListing(market)
    for _, row in df.iterrows():
        name = str(row["Name"]).strip()
        code = str(row["Code"]).strip().zfill(6)
        if not name:
            continue
        # Build name aliases: name with/without spaces, common short forms
        aliases = {name}
        aliases.add(name.replace(" ", ""))
        # Common Korean stock nicknames
        if name == "삼성전자":
            aliases.update(["삼전"])
        elif name == "SK하이닉스":
            aliases.update(["하이닉스", "SK하닉", "하닉"])
        elif name == "LG에너지솔루션":
            aliases.update(["LG엔솔", "엘지엔솔", "LGES"])
        elif name == "삼성SDI":
            aliases.update(["삼성에스디아이"])
        elif name == "두산에너빌리티":
            aliases.update(["두산에빌"])
        elif name == "HD현대중공업":
            aliases.update(["현대중공업"])
        elif name == "HD현대일렉트릭":
            aliases.update(["현대일렉트릭", "현대엘렉트릭", "현대일렉"])
        elif name == "HD한국조선해양":
            aliases.update(["한국조선해양"])
        elif name == "HD현대마린솔루션":
            aliases.update(["현대마린솔루션"])
        elif name == "HD현대미포":
            aliases.update(["현대미포조선", "현대미포"])
        elif name == "HD현대인프라코어":
            aliases.update(["현대인프라코어"])
        elif name == "HD현대건설기계":
            aliases.update(["현대건설기계"])
        elif name == "HD현대":
            aliases.update(["현대중공업지주"])
        elif name == "한화에어로스페이스":
            aliases.update(["한화에어로"])
        elif name == "현대일렉트릭":
            aliases.update(["현대엘렉트릭", "현대일렉"])
        elif name == "현대모비스":
            aliases.update(["모비스"])
        records.append({
            "code": code,
            "name": name,
            "market": market,
            "aliases": sorted(aliases),
        })

# Save
OUT.write_text(json.dumps(records, ensure_ascii=False, indent=2))
print(f"Saved {len(records)} tickers to {OUT}")
print(f"  KOSPI:  {sum(1 for r in records if r['market']=='KOSPI')}")
print(f"  KOSDAQ: {sum(1 for r in records if r['market']=='KOSDAQ')}")
print(f"File size: {OUT.stat().st_size//1024} KB")
