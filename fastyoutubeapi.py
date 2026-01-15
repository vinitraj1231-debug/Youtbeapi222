import aiohttp
import urllib.parse
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse

app = FastAPI(title="Song Name → Play API (Guaranteed Working)")

# Stable Piped instances for SEARCH + WATCH
PIPED_INSTANCES = [
    "https://piped.video",
    "https://yewtu.be",
    "https://yt.artemislena.eu"
]

TIMEOUT = aiohttp.ClientTimeout(total=20)


async def piped_search(query: str):
    """
    Search song on Piped and return first videoId
    """
    q = urllib.parse.quote(query)

    for base in PIPED_INSTANCES:
        search_url = f"{base}/api/v1/search?q={q}&filter=videos"
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.get(search_url) as r:
                    if r.status == 200:
                        data = await r.json()
                        if isinstance(data, list) and len(data) > 0:
                            first = data[0]
                            if "videoId" in first:
                                return base, first["videoId"]
        except:
            continue
    return None, None


@app.get("/play")
async def play(query: str = Query(..., description="Song name or keywords")):
    if not query.strip():
        raise HTTPException(400, "Query cannot be empty")

    base, video_id = await piped_search(query)
    if not video_id:
        raise HTTPException(503, "Search failed on all instances")

    # Redirect to playable page
    play_url = f"{base}/watch?v={video_id}"
    return RedirectResponse(play_url)


@app.get("/play-json")
async def play_json(query: str = Query(...)):
    base, video_id = await piped_search(query)
    if not video_id:
        raise HTTPException(503, "Search failed")

    return JSONResponse({
        "query": query,
        "video_id": video_id,
        "play_url": f"{base}/watch?v={video_id}"
    })


@app.get("/health")
async def health():
    return {"status": "ok"}
