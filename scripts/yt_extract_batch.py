"""Batch process all transcripts with chosen model. Idempotent - skips existing outputs.

Usage: python3 yt_extract_batch.py [model] [transcripts_dir] [out_dir]
"""
import json
import sys
import time
from pathlib import Path
from yt_extract_v2 import extract
from ticker_normalize import normalize_extraction

sys.path.insert(0, str(Path(__file__).parent))
from config import channel_paths, EXTRACTION_MODEL

MODEL = sys.argv[1] if len(sys.argv) > 1 else EXTRACTION_MODEL
_default_paths = channel_paths("han_gyunsoo")
TRANSCRIPTS = Path(sys.argv[2]) if len(sys.argv) > 2 else _default_paths["transcripts"]
OUT_DIR = Path(sys.argv[3]) if len(sys.argv) > 3 else _default_paths["extractions"]
OUT_DIR.mkdir(parents=True, exist_ok=True)
print(f"Model: {MODEL}")
print(f"Transcripts: {TRANSCRIPTS}")
print(f"Output: {OUT_DIR}")

files = sorted(TRANSCRIPTS.glob("*.json"))
total_cost = 0.0
total_in = 0
total_out = 0
results = []

for i, f in enumerate(files, 1):
    out_path = OUT_DIR / f"{f.stem}_{MODEL}.json"
    if out_path.exists():
        print(f"[{i:2}/{len(files)}] SKIP {f.stem} (exists)", flush=True)
        existing = json.loads(out_path.read_text())
        results.append(existing)
        total_cost += existing["_meta"]["cost_usd"]
        total_in += existing["_meta"]["input_tokens"]
        total_out += existing["_meta"]["output_tokens"]
        continue

    t0 = time.time()
    try:
        result = extract(f, MODEL)
        result = normalize_extraction(result)
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        m = result["_meta"]
        norm = result["_ticker_normalization"]
        elapsed = time.time() - t0
        themes = len(result["themes"])
        policies = len(result["policy_diplomatic_mentions"])
        total_cost += m["cost_usd"]
        total_in += m["input_tokens"]
        total_out += m["output_tokens"]
        results.append(result)
        unc = "U" if result.get("uncertain") else "."
        print(f"[{i:2}/{len(files)}] OK[{unc}] {f.stem} | T={themes} P={policies} | tk(ex/fz/fr/un)={norm['exact']}/{norm['fuzzy']}/{norm['foreign']}/{norm['unknown']} | {elapsed:.1f}s | ${m['cost_usd']:.5f}", flush=True)
    except Exception as e:
        print(f"[{i:2}/{len(files)}] ERR  {f.stem} | {type(e).__name__}: {e}", flush=True)

print("---")
print(f"Total cost: ${total_cost:.4f}  ({total_cost*1400:.0f}원 추정)")
print(f"Total tokens: in={total_in:,} out={total_out:,}")
print(f"Files OK: {sum(1 for _ in OUT_DIR.glob(f'*_{MODEL}.json'))}/{len(files)}")
