from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import aiohttp

app = FastAPI(title="Working YouTube Audio API")

PIPED_INSTANCES = [
    "https://piped.video",
    "https://yewtu.be",
    "https://yt.artemislena.eu"
]

async def fetch_from_piped(video_id: str):
    for base in PIPED_INSTANCES:
        try:
            url = f"{base}/api/v1/streams/{video_id}"
            async with aiohttp.ClientSession() as session:
                async with session.get(url, timeout=20) as r:
                    if r.status == 200:
                        return await r.json()
        except:
            continue
    return None


@app.get("/download")
async def download_audio(url: str = Query(...)):
    if "v=" not in url:
        raise HTTPException(status_code=400, detail="Invalid YouTube URL")

    video_id = url.split("v=")[-1].split("&")[0]

    data = await fetch_from_piped(video_id)
    if not data:
        raise HTTPException(status_code=500, detail="All Piped instances failed")

    audio_streams = [
        s for s in data.get("audioStreams", [])
        if s.get("mimeType", "").startswith("audio")
    ]

    if not audio_streams:
        raise HTTPException(status_code=404, detail="No audio stream found")

    best_audio = max(audio_streams, key=lambda x: x.get("bitrate", 0))

    return JSONResponse({
        "title": data.get("title"),
        "duration": data.get("duration"),
        "thumbnail": data.get("thumbnailUrl"),
        "audio_url": best_audio.get("url"),
        "bitrate": best_audio.get("bitrate")
    })
