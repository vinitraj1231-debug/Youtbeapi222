from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import StreamingResponse
import yt_dlp
import asyncio
import os
import tempfile

app = FastAPI(title="YouTube Audio Download API")

YDL_OPTS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True,
    "cookiefile": None,  # important: no cookies
    "nocheckcertificate": True,
    "geo_bypass": True,
    "extractor_args": {
        "youtube": {
            "skip": ["dash", "hls"]
        }
    }
}

@app.get("/download")
async def download_audio(url: str = Query(...)):
    loop = asyncio.get_event_loop()

    try:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        file_path = tmp.name
        tmp.close()

        def run_ydl():
            with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
                ydl.download([url])

        await loop.run_in_executor(None, run_ydl)

        if not os.path.exists(file_path):
            raise Exception("Audio file not created")

        return StreamingResponse(
            open(file_path, "rb"),
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=audio.mp3"
            }
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
