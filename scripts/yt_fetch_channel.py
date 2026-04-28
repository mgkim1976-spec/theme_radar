"""Fetch all transcripts from a channel's uploads playlist.

Usage: python3 yt_fetch_channel.py <channel_id> <output_subdir> [max_videos]
Example: python3 yt_fetch_channel.py UCadSWH0pDXxEatvLHEHCWlg han_gyunsoo

Rate limit protection:
- 2.5-5s jitter between video requests
- 60s rest every 25 videos
- Exponential backoff on 429/IpBlocked (60s, 2m, 4m, 8m, 16m)
- Aborts entire run if 5 consecutive 429s occur (saves work)
"""
import json
import os
import random
import sys
import subprocess
import time
from pathlib import Path
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.proxies import GenericProxyConfig
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable, IpBlocked,
    RequestBlocked,
)

sys.path.insert(0, str(Path(__file__).parent))
from config import YOUTUBE_DATA

CHANNEL_ID = sys.argv[1]
SUBDIR = sys.argv[2]
MAX_VIDEOS = int(sys.argv[3]) if len(sys.argv) > 3 else 99999
BASE = YOUTUBE_DATA / SUBDIR
OUT_DIR = BASE / "transcripts"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Rate-limit tunables (relaxed when using residential proxy)
PROXY_URL = os.environ.get("WEBSHARE_PROXY_URL")  # http://user:pwd@p.webshare.io:80
USE_PROXY = bool(PROXY_URL)

JITTER_MIN = 4.0 if USE_PROXY else 2.5
JITTER_MAX = 7.0 if USE_PROXY else 5.0
BATCH_REST_EVERY = 50 if USE_PROXY else 25
BATCH_REST_SECONDS = 15 if USE_PROXY else 60
BACKOFF_BASE = 30 if USE_PROXY else 60
BACKOFF_MAX_RETRIES = 5
ABORT_AFTER_CONSECUTIVE_BLOCKS = 5

# Build uploads playlist URL: UC -> UU
uploads_id = "UU" + CHANNEL_ID[2:]
url = f"https://www.youtube.com/playlist?list={uploads_id}"

# Fetch ID + upload_date + title via yt-dlp (one call)
print(f"Listing channel {CHANNEL_ID} uploads...", flush=True)
res = subprocess.run(
    ["yt-dlp", "--flat-playlist", "--no-warnings",
     "--print", "%(id)s|%(title)s", url],
    capture_output=True, text=True, timeout=300,
)
lines = [l for l in res.stdout.strip().split("\n") if l and "|" in l]
print(f"Found {len(lines)} videos in playlist", flush=True)

def fetch_transcript_with_backoff(api, vid):
    """Try to fetch transcript; on IpBlocked/RequestBlocked, exp backoff and retry."""
    for attempt in range(BACKOFF_MAX_RETRIES):
        try:
            listing = api.list(vid)
            try:
                tr = listing.find_manually_created_transcript(["ko"])
                kind = "manual"
            except NoTranscriptFound:
                tr = listing.find_generated_transcript(["ko"])
                kind = "auto"
            return tr.fetch(), tr.language_code, kind
        except (IpBlocked, RequestBlocked) as e:
            if attempt == BACKOFF_MAX_RETRIES - 1:
                raise
            wait = BACKOFF_BASE * (2 ** attempt)
            print(f"  -> 429/IpBlocked, backoff {wait}s (attempt {attempt+1}/{BACKOFF_MAX_RETRIES})", flush=True)
            time.sleep(wait)


# Limit to MAX_VIDEOS
if len(lines) > MAX_VIDEOS:
    print(f"Limiting to first {MAX_VIDEOS} videos (newest)", flush=True)
    lines = lines[:MAX_VIDEOS]

if USE_PROXY:
    proxy_cfg = GenericProxyConfig(http_url=PROXY_URL, https_url=PROXY_URL)
    api = YouTubeTranscriptApi(proxy_config=proxy_cfg)
    print(f"Using Webshare residential proxy", flush=True)
else:
    api = YouTubeTranscriptApi()
    print(f"Direct connection (no proxy)", flush=True)

ok = skip = fail = 0
consecutive_blocks = 0

for i, line in enumerate(lines, 1):
    vid, title = line.split("|", 1)

    # Get upload date (yt-dlp metadata - rarely rate-limited)
    res = subprocess.run(
        ["yt-dlp", "--skip-download", "--no-warnings",
         "--print", "%(upload_date)s", f"https://www.youtube.com/watch?v={vid}"],
        capture_output=True, text=True, timeout=30,
    )
    date_lines = [l for l in res.stdout.strip().split("\n")
                  if l and l.isdigit() and len(l) == 8]
    if not date_lines:
        print(f"[{i:4}/{len(lines)}] PRIVATE/NOPUB {vid} {title[:40]}", flush=True)
        fail += 1
        continue
    date = date_lines[0]

    out_path = OUT_DIR / f"{date}_{vid}.json"
    if out_path.exists():
        skip += 1
        print(f"[{i:4}/{len(lines)}] SKIP  {date} {vid} {title[:40]}", flush=True)
        continue

    try:
        fetched, lang, kind = fetch_transcript_with_backoff(api, vid)
        segments = [{"start": s.start, "duration": s.duration, "text": s.text} for s in fetched]
        full_text = " ".join(s["text"] for s in segments)
        payload = {
            "video_id": vid,
            "upload_date": date,
            "title": title,
            "language": lang,
            "kind": kind,
            "segment_count": len(segments),
            "char_count": len(full_text),
            "segments": segments,
            "full_text": full_text,
        }
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
        ok += 1
        consecutive_blocks = 0
        print(f"[{i:4}/{len(lines)}] OK    {date} {vid} {kind} {len(full_text):,}c {title[:40]}", flush=True)
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        fail += 1
        consecutive_blocks = 0
        print(f"[{i:4}/{len(lines)}] NOCAP {vid} {type(e).__name__}", flush=True)
    except (IpBlocked, RequestBlocked) as e:
        fail += 1
        consecutive_blocks += 1
        print(f"[{i:4}/{len(lines)}] BLOCK {vid} (consecutive={consecutive_blocks})", flush=True)
        if consecutive_blocks >= ABORT_AFTER_CONSECUTIVE_BLOCKS:
            print(f"\n!!! Aborting: {ABORT_AFTER_CONSECUTIVE_BLOCKS} consecutive blocks. IP banned, try later.", flush=True)
            break
    except Exception as e:
        fail += 1
        print(f"[{i:4}/{len(lines)}] ERROR {vid} {type(e).__name__}: {e}", flush=True)

    # Jitter between requests
    time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))

    # Periodic batch rest
    if i % BATCH_REST_EVERY == 0 and i < len(lines):
        print(f"  -- batch rest {BATCH_REST_SECONDS}s after {i} videos --", flush=True)
        time.sleep(BATCH_REST_SECONDS)

print(f"---\nOK={ok} SKIP={skip} FAIL={fail}  Total in dir: {len(list(OUT_DIR.glob('*.json')))}")
