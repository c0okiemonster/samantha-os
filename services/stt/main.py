"""
Samantha OS — Speech-to-Text Service
Uses Faster-Whisper for local, fast transcription.
"""

import os
import io
import subprocess
import tempfile
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, File
from faster_whisper import WhisperModel

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "en")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stt")

model: WhisperModel | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global model
    logger.info(f"Loading Whisper model: {WHISPER_MODEL} on {WHISPER_DEVICE}")
    compute_type = "int8" if WHISPER_DEVICE == "cpu" else "float16"
    model = WhisperModel(
        WHISPER_MODEL,
        device=WHISPER_DEVICE,
        compute_type=compute_type,
    )
    logger.info("✅ Whisper model loaded")
    yield
    logger.info("STT service shutting down")


app = FastAPI(title="Samantha STT", lifespan=lifespan)


def _convert_to_wav(audio_bytes: bytes) -> bytes:
    """Convert any audio format to 16kHz mono WAV using ffmpeg."""
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as infile:
        infile.write(audio_bytes)
        in_path = infile.name

    out_path = in_path + ".wav"
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", in_path, "-ar", "16000", "-ac", "1",
             "-f", "wav", out_path],
            capture_output=True, timeout=15,
        )
        if result.returncode != 0:
            logger.warning(f"ffmpeg stderr: {result.stderr.decode()[:300]}")
            return audio_bytes  # fallback to original

        with open(out_path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"Audio conversion failed: {e}")
        return audio_bytes
    finally:
        for p in (in_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


@app.get("/health")
async def health():
    return {"status": "ok" if model else "loading", "model": WHISPER_MODEL}


@app.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    """Transcribe audio file to text."""
    if not model:
        return {"error": "Model not loaded yet"}

    audio_bytes = await audio.read()

    # Convert to WAV (handles webm, opus, mp3, etc.)
    wav_bytes = _convert_to_wav(audio_bytes)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(wav_bytes)
        tmp_path = tmp.name

    try:
        language = WHISPER_LANGUAGE if WHISPER_LANGUAGE != "auto" else None
        segments, info = model.transcribe(
            tmp_path,
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(
                onset=0.15,
                min_silence_duration_ms=600,
                speech_pad_ms=400,
                min_speech_duration_ms=100,
            ),
        )

        text_parts = []
        for segment in segments:
            text_parts.append(segment.text.strip())

        full_text = " ".join(text_parts)
        logger.info(f"Transcribed ({info.language}, {info.duration:.1f}s): {full_text}")

        return {
            "text": full_text,
            "language": info.language,
            "duration": info.duration,
        }

    finally:
        os.unlink(tmp_path)
