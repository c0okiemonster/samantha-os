import os
import wave

from integrations.tasks.chime import ensure_chime_exists


def test_creates_file_if_missing(tmp_path):
    path = tmp_path / "chime.wav"
    assert not path.exists()
    ensure_chime_exists(str(path))
    assert path.exists()
    assert path.stat().st_size > 0


def test_idempotent(tmp_path):
    path = tmp_path / "chime.wav"
    ensure_chime_exists(str(path))
    first_mtime = path.stat().st_mtime
    ensure_chime_exists(str(path))
    assert path.stat().st_mtime == first_mtime


def test_wav_is_valid_24khz_mono_pcm16(tmp_path):
    path = tmp_path / "chime.wav"
    ensure_chime_exists(str(path))
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1
        assert w.getframerate() == 24000
        assert w.getsampwidth() == 2


def test_duration_roughly_800ms(tmp_path):
    path = tmp_path / "chime.wav"
    ensure_chime_exists(str(path))
    with wave.open(str(path), "rb") as w:
        duration_s = w.getnframes() / w.getframerate()
    assert 0.75 <= duration_s <= 0.85


def test_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "dir" / "chime.wav"
    ensure_chime_exists(str(path))
    assert path.exists()
