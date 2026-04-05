"""
Samantha OS — TTS using Kokoro KPipeline
Supports:
  - Voice blending (nicole + sky → samantha)
  - Markdown pronunciation syntax: [word](/IPA/)
  - Stress control: [word](+1), [word](-1)
  - Natural punctuation and pauses
"""

import os
import io
import logging
from contextlib import asynccontextmanager

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI
from pydantic import BaseModel

KOKORO_VOICE = os.getenv("KOKORO_VOICE", "samantha")
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "0.90"))
KOKORO_LANG = os.getenv("KOKORO_LANG", "a")  # 'a' = American English

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tts")

pipeline = None
samantha_voice_tensor = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global pipeline, samantha_voice_tensor
    logger.info("Loading Kokoro KPipeline...")
    try:
        from kokoro import KPipeline
        pipeline = KPipeline(lang_code=KOKORO_LANG)

        # Build blended voice tensor: nicole 45% + sky 55%
        # Load individual voice tensors from the pipeline
        nicole = pipeline.load_voice("af_nicole")
        sky = pipeline.load_voice("af_sky")
        samantha_voice_tensor = nicole * 0.45 + sky * 0.55

        logger.info(f"Kokoro ready — voice: samantha (nicole 45% + sky 55%)")
    except Exception as e:
        logger.error(f"Failed: {e}")
        import traceback
        traceback.print_exc()
    yield


app = FastAPI(title="Samantha TTS", lifespan=lifespan)


class SynthesizeRequest(BaseModel):
    text: str
    speed: float | None = None
    voice: str | None = None


@app.get("/health")
async def health():
    return {"status": "ok" if pipeline else "loading", "voice": KOKORO_VOICE, "engine": "kokoro-kpipeline"}


@app.post("/synthesize")
async def synthesize(req: SynthesizeRequest):
    if not pipeline:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "TTS not ready"}, status_code=503)

    text = req.text.strip()
    if not text:
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Empty text"}, status_code=400)

    speed = req.speed or KOKORO_SPEED
    voice = samantha_voice_tensor if (req.voice or KOKORO_VOICE) == "samantha" else (req.voice or KOKORO_VOICE)

    logger.info(f"Synth @{speed}x: {text[:60]}...")

    try:
        # KPipeline yields (grapheme_string, phoneme_string, audio)
        all_audio = []
        generator = pipeline(text, voice=voice, speed=speed)
        for i, (gs, ps, audio) in enumerate(generator):
            if audio is not None:
                if isinstance(audio, torch.Tensor):
                    audio = audio.cpu().numpy()
                all_audio.append(audio)

        if not all_audio:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": "No audio generated"}, status_code=500)

        combined = np.concatenate(all_audio)
        buf = io.BytesIO()
        sf.write(buf, combined, 24000, format="WAV")

        from fastapi.responses import Response
        return Response(content=buf.getvalue(), media_type="audio/wav")

    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        import traceback
        traceback.print_exc()
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": str(e)}, status_code=500)
