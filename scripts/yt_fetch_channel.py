"""Fetch all transcripts from a channel's uploads playlist.

Usage: python3 yt_fetch_channel.py <channel_id> <output_subdir> [max_videos]
Example: python3 yt_fetch_channel.py UCadSWH0pDXxEatvLHEHCWlg han_gyunsoo

Rate limit protection (v2):
- ThreadPoolExecutor parallel fetch (default 5 workers, env FETCH_WORKERS)
- 1-3s jitter per worker (paid proxy tier — relaxed from 4-7s)
- 5s rest every 50 videos
- Exponential backoff on 429/IpBlocked (30s, 1m, 2m, 4m, 8m)
- Aborts entire run if 5 consecutive 429s occur
"""
import json
import os
import random
import sys
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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

# Rate-limit tunables (paid Webshare tier — aggressive)
PROXY_URL = os.environ.get("WEBSHARE_PROXY_URL")
USE_PROXY = bool(PROXY_URL)
WORKERS = int(os.environ.get("FETCH_WORKERS", "5" if USE_PROXY else "1"))

JITTER_MIN = 1.0 if USE_PROXY else 2.5
JITTER_MAX = 3.0 if USE_PROXY else 5.0
BATCH_REST_EVERY = 50 if USE_PROXY else 25
BATCH_REST_SECONDS = 5 if USE_PROXY else 60
BACKOFF_BASE = 30 if USE_PROXY else 60
BACKOFF_MAX_RETRIES = 5
ABORT_AFTER_CONSECUTIVE_BLOCKS = 5

# Build uploads playlist URL: UC -> UU
uploads_id = "UU" + CHANNEL_ID[2:]
url = f"https://www.youtube.com/playlist?list={uploads_id}"

# Fetch ID + title via yt-dlp (one call, fast metadata)
print(f"Listing channel {CHANNEL_ID} uploads...", flush=True)
res = subprocess.run(
    ["yt-dlp", "--flat-playlist", "--no-warnings",
     "--print", "%(id)s|%(title)s", url],
    capture_output=True, text=True, timeout=300,
)
lines = [l for l in res.stdout.strip().split("\n") if l and "|" in l]
print(f"Found {len(lines)} videos in playlist", flush=True)

if len(lines) > MAX_VIDEOS:
    print(f"Limiting to first {MAX_VIDEOS} videos (newest)", flush=True)
    lines = lines[:MAX_VIDEOS]


# ============================================================
# Thread-safe stats + log
# ============================================================
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.print_lock = threading.Lock()
        self.ok = 0
        self.skip = 0
        self.fail = 0
        self.consecutive_blocks = 0
        self.aborted = False

    def log(self, msg):
        with self.print_lock:
            print(msg, flush=True)

    def inc_ok(self):
        with self.lock:
            self.ok += 1
            self.consecutive_blocks = 0

    def inc_skip(self):
        with self.lock:
            self.skip += 1

    def inc_fail(self, blocked=False):
        with self.lock:
            self.fail += 1
            if blocked:
                self.consecutive_blocks += 1
                if self.consecutive_blocks >= ABORT_AFTER_CONSECUTIVE_BLOCKS:
                    self.aborted = True
            else:
                self.consecutive_blocks = 0

    def is_aborted(self):
        with self.lock:
            return self.aborted


state = State()


def make_api():
    """Per-worker API instance (thread-safe by isolation)."""
    if USE_PROXY:
        proxy_cfg = GenericProxyConfig(http_url=PROXY_URL, https_url=PROXY_URL)
        return YouTubeTranscriptApi(proxy_config=proxy_cfg)
    return YouTubeTranscriptApi()


_thread_local = threading.local()


def get_api():
    if not hasattr(_thread_local, "api"):
        _thread_local.api = make_api()
    return _thread_local.api


def fetch_transcript_with_backoff(vid):
    """Try to fetch; backoff on IpBlocked/RequestBlocked."""
    api = get_api()
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
        except (IpBlocked, RequestBlocked):
            if attempt == BACKOFF_MAX_RETRIES - 1:
                raise
            wait = BACKOFF_BASE * (2 ** attempt)
            state.log(f"  -> 429/IpBlocked, backoff {wait}s (attempt {attempt+1}/{BACKOFF_MAX_RETRIES})")
            time.sleep(wait)


def process_one(idx_total: tuple, line: str):
    """Worker — process single video. Idempotent skip + transcript fetch + save."""
    if state.is_aborted():
        return
    i, total = idx_total
    vid, title = line.split("|", 1)

    # Get upload date (yt-dlp metadata)
    try:
        res = subprocess.run(
            ["yt-dlp", "--skip-download", "--no-warnings",
             "--print", "%(upload_date)s", f"https://www.youtube.com/watch?v={vid}"],
            capture_output=True, text=True, timeout=30,
        )
        date_lines = [l for l in res.stdout.strip().split("\n")
                      if l and l.isdigit() and len(l) == 8]
        if not date_lines:
            state.log(f"[{i:4}/{total}] PRIVATE/NOPUB {vid} {title[:40]}")
            state.inc_fail()
            return
        date = date_lines[0]
    except Exception as ex:
        state.log(f"[{i:4}/{total}] METADATA_ERR {vid} {type(ex).__name__}")
        state.inc_fail()
        return

    out_path = OUT_DIR / f"{date}_{vid}.json"
    if out_path.exists():
        state.inc_skip()
        state.log(f"[{i:4}/{total}] SKIP  {date} {vid} {title[:40]}")
        return

    try:
        fetched, lang, kind = fetch_transcript_with_backoff(vid)
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
        state.inc_ok()
        state.log(f"[{i:4}/{total}] OK    {date} {vid} {kind} {len(full_text):,}c {title[:40]}")
    except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
        state.inc_fail()
        state.log(f"[{i:4}/{total}] NOCAP {vid} {type(e).__name__}")
    except (IpBlocked, RequestBlocked):
        state.inc_fail(blocked=True)
        with state.lock:
            cb = state.consecutive_blocks
        state.log(f"[{i:4}/{total}] BLOCK {vid} (consecutive={cb})")
    except Exception as e:
        state.inc_fail()
        state.log(f"[{i:4}/{total}] ERROR {vid} {type(e).__name__}: {e}")

    # Per-worker jitter (smaller — paid tier)
    time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))


# ============================================================
# Main loop — parallel
# ============================================================
total = len(lines)
print(f"Workers: {WORKERS} | jitter {JITTER_MIN}-{JITTER_MAX}s | "
      f"batch rest {BATCH_REST_SECONDS}s every {BATCH_REST_EVERY}", flush=True)
print(f"{'Using Webshare residential proxy' if USE_PROXY else 'Direct connection (no proxy)'}", flush=True)

# Submit all jobs to thread pool — workers pick them up
with ThreadPoolExecutor(max_workers=WORKERS) as executor:
    futures = []
    for i, line in enumerate(lines, 1):
        if state.is_aborted():
            break
        futures.append(executor.submit(process_one, (i, total), line))

        # Periodic batch rest — main thread pauses submission
        if i % BATCH_REST_EVERY == 0 and i < total:
            # Wait for current batch to roughly complete then short rest
            time.sleep(BATCH_REST_SECONDS)

    # Wait for all to finish
    for f in as_completed(futures):
        try:
            f.result()
        except Exception as e:
            state.log(f"  worker exception: {type(e).__name__}: {e}")

if state.aborted:
    print(f"\n!!! Aborted: {ABORT_AFTER_CONSECUTIVE_BLOCKS} consecutive blocks. IP banned, try later.", flush=True)

print(f"---\nOK={state.ok} SKIP={state.skip} FAIL={state.fail}  "
      f"Total in dir: {len(list(OUT_DIR.glob('*.json')))}")
