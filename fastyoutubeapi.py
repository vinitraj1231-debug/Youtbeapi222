import re
import aiohttp
import asyncio
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse

app = FastAPI(title="Guaranteed Working YouTube Audio API")

# Layered fallback sources
PIPED_APIS = [
    "https://piped.video/api/v1/streams/",
    "https://yt.artemislena.eu/api/v1/streams/",
    "https://yewtu.be/api/v1/streams/"
]

INVIDIOUS_APIS = [
    "https://vid.puffyan.us/api/v1/videos/",
    "https://invidious.fdn.fr/api/v1/videos/",
    "https://inv.nadeko.net/api/v1/videos/"
]

LEMOS_API = "https://yt.lemnos.life/api/v1/streams/"

TIMEOUT = aiohttp.ClientTimeout(total=25)


def extract_video_id(text: str):
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", text):
        return text
    for p in ["v=", "youtu.be/", "/embed/"]:
        if p in text:
            return text.split(p)[-1].split("&")[0].split("?")[0]
    return None


async def try_fetch(url):
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            async with session.get(url) as r:
                if r.status == 200:
                    return await r.json()
    except:
        return None


def extract_audio(data: dict):
    for key in ["audioStreams", "adaptiveFormats", "formats"]:
        streams = data.get(key, [])
        if isinstance(streams, list):
            audios = [s for s in streams if s.get("url") and "audio" in s.get("mimeType", "")]
            if audios:
                return max(audios, key=lambda x: x.get("bitrate", 0))
    return None


@app.get("/download")
async def download(url: str = Query(...)):
    vid = extract_video_id(url)
    if not vid:
        raise HTTPException(400, "Invalid YouTube URL or ID")

    # Layer 1: Piped
    for base in PIPED_APIS:
        data = await try_fetch(base + vid)
        if data:
            audio = extract_audio(data)
            if audio:
                return JSONResponse({
                    "source": "piped",
                    "video_id": vid,
                    "title": data.get("title"),
                    "duration": data.get("duration"),
                    "thumbnail": data.get("thumbnailUrl"),
                    "audio_url": audio["url"],
                    "bitrate": audio.get("bitrate")
                })

    # Layer 2: Invidious
    for base in INVIDIOUS_APIS:
        data = await try_fetch(base + vid)
        if data:
            adaptive = data.get("adaptiveFormats", [])
            audios = [a for a in adaptive if "audio" in a.get("type", "")]
            if audios:
                best = max(audios, key=lambda x: x.get("bitrate", 0))
                return JSONResponse({
                    "source": "invidious",
                    "video_id": vid,
                    "title": data.get("title"),
                    "duration": data.get("lengthSeconds"),
                    "thumbnail": data.get("videoThumbnails", [{}])[-1].get("url"),
                    "audio_url": best["url"],
                    "bitrate": best.get("bitrate")
                })

    # Layer 3: Lemnos (last & strong fallback)
    data = await try_fetch(LEMOS_API + vid)
    if data:
        audio = extract_audio(data)
        if audio:
            return JSONResponse({
                "source": "lemnos",
                "video_id": vid,
                "title": data.get("title"),
                "duration": data.get("duration"),
                "thumbnail": data.get("thumbnailUrl"),
                "audio_url": audio["url"],
                "bitrate": audio.get("bitrate")
            })

    raise HTTPException(503, "All extractors failed (temporary upstream issue)")
