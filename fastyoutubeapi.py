import re
import aiohttp
import asyncio
import urllib.parse
from typing import Optional, Dict, Any, List

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Reliable YouTube Audio API (Piped-backed)")

# Piped / Invidious instances (ordered by preference). You can add / remove entries.
PIPED_INSTANCES = [
    "https://piped.video",
    "https://yewtu.be",
    "https://yt.artemislena.eu"
]

# HTTP request settings
REQUEST_TIMEOUT = 20  # seconds
MAX_INSTANCE_RETRY = 3  # per instance attempts (best-effort)


def extract_video_id(input_value: str) -> Optional[str]:
    """
    Extract YouTube video id from a variety of inputs:
    - Full URL (https://www.youtube.com/watch?v=ID or with extra params)
    - Short youtu.be/ID
    - Plain ID (11 chars)
    - Embedded URL formats
    Returns video_id (11-char) or None
    """
    if not input_value:
        return None

    s = input_value.strip()

    # If input already looks like a raw ID (11 chars, allowed chars)
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", s):
        return s

    # Try youtu.be short link
    m = re.search(r"(?:youtu\.be/)([0-9A-Za-z_-]{11})", s)
    if m:
        return m.group(1)

    # Try common watch?v= format
    m = re.search(r"[?&]v=([0-9A-Za-z_-]{11})", s)
    if m:
        return m.group(1)

    # Try embed URLs /v/ or /embed/
    m = re.search(r"(?:/embed/|/v/)([0-9A-Za-z_-]{11})", s)
    if m:
        return m.group(1)

    # Last resort: find the first 11-char candidate
    m = re.search(r"([0-9A-Za-z_-]{11})", s)
    if m:
        return m.group(1)

    return None


async def fetch_from_piped(video_id: str) -> Optional[Dict[str, Any]]:
    """
    Try multiple Piped/Invidious instances to get stream metadata.
    Returns parsed JSON from the first successful instance, or None.
    """
    if not video_id:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*"
    }

    for base in PIPED_INSTANCES:
        # try each instance up to MAX_INSTANCE_RETRY attempts (best-effort)
        for attempt in range(MAX_INSTANCE_RETRY):
            try:
                url = f"{base.rstrip('/')}/api/v1/streams/{urllib.parse.quote(video_id)}"
                timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            try:
                                data = await resp.json()
                                # basic validation
                                if isinstance(data, dict) and ("title" in data):
                                    return data
                                # if response isn't structured as expected, continue to next instance
                            except Exception:
                                # malformed json or decode error -> try next
                                pass
                        # non-200 -> try again or next instance
            except asyncio.TimeoutError:
                # try again (maybe transient)
                continue
            except Exception:
                # network / dns / ssl error -> try next instance
                break
    return None


def select_best_audio_stream(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Given the parsed JSON from a Piped/Invidious instance,
    locate the best audio stream and return its dict containing at least 'url' and 'bitrate' (if available).
    Supports multiple possible response shapes.
    """
    # 1) piped style: 'audioStreams' (list)
    audio_streams = data.get("audioStreams") or []
    if isinstance(audio_streams, list) and audio_streams:
        candidates = [s for s in audio_streams if isinstance(s, dict) and s.get("url")]
        if candidates:
            # choose by bitrate if present, else by contentLength or fallback to first
            def score(s: Dict[str, Any]):
                return s.get("bitrate") or s.get("contentLength") or 0
            return max(candidates, key=score)

    # 2) some instances provide 'adaptiveFormats' or 'streams'
    for key in ("adaptiveFormats", "streams", "formats"):
        arr = data.get(key) or []
        if isinstance(arr, list) and arr:
            candidates = [s for s in arr if isinstance(s, dict) and s.get("url") and s.get("mimeType", "").startswith("audio")]
            if candidates:
                def score(s: Dict[str, Any]):
                    return s.get("bitrate") or s.get("contentLength") or 0
                return max(candidates, key=score)

    # 3) older / alternative field names
    # look for any dict in top-level with url + audio mime
    def is_audio_candidate(x):
        return isinstance(x, dict) and x.get("url") and "audio" in (x.get("mimeType", "") or "")

    # scan nested lists/dicts shallowly
    stack: List[Any] = [data]
    visited = set()
    while stack:
        node = stack.pop()
        if id(node) in visited:
            continue
        visited.add(id(node))
        if isinstance(node, dict):
            for v in node.values():
                if is_audio_candidate(v):
                    return v
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(node, list):
            for item in node:
                if is_audio_candidate(item):
                    return item
                if isinstance(item, (dict, list)):
                    stack.append(item)

    return None


@app.get("/download")
async def download_audio(url: str = Query(..., description="YouTube URL or video id")):
    """
    Returns JSON with metadata and a direct audio URL (streamable).
    Example: /download?url=https://youtu.be/BddP6PYo2gs
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL or ID")

    data = await fetch_from_piped(video_id)
    if not data:
        raise HTTPException(status_code=502, detail="All Piped/Invidious instances failed or returned unexpected data")

    audio = select_best_audio_stream(data)
    if not audio:
        raise HTTPException(status_code=404, detail="No audio stream found in instance response")

    # Normalize response fields
    title = data.get("title") or data.get("videoTitle") or ""
    duration = data.get("duration")  # may be seconds (int) or string
    thumbnail = data.get("thumbnailUrl") or data.get("thumbnail") or data.get("videoThumbnails")
    audio_url = audio.get("url")
    bitrate = audio.get("bitrate") or audio.get("contentLength") or None
    mime = audio.get("mimeType") or audio.get("type") or None

    return JSONResponse({
        "video_id": video_id,
        "title": title,
        "duration": duration,
        "thumbnail": thumbnail,
        "audio_url": audio_url,
        "bitrate": bitrate,
        "mime_type": mime,
        "source_instance": data.get("source") or None
    })


@app.get("/health")
async def health():
    return {"status": "ok"}
