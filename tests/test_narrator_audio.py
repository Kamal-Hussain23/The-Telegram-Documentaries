"""The PCM → OGG/Opus transcoder: ffmpeg discovery and output contract.

Reference: SPECS/2026-10-11-narrator/plan.md group 1, validation.md check 3.
Transcoding to real OGG requires an ffmpeg binary; without one the encoder
tests skip and the suite stays green offline.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Iterator

import pytest
from telegram_documentaries.narrator_audio import (
    AUDIO_MIME_TYPES,
    PCM_SAMPLE_RATE,
    AudioTranscodeError,
    find_ffmpeg,
    pcm_to_ogg,
)


@pytest.fixture(autouse=True)
def _clear_ffmpeg_cache() -> Iterator[None]:
    """Stop the cached encoder lookup leaking between (monkeypatched) tests."""
    find_ffmpeg.cache_clear()
    yield
    find_ffmpeg.cache_clear()


def _pcm(seconds: float = 0.5, rate: int = PCM_SAMPLE_RATE) -> bytes:
    """A few hundred ms of 440 Hz sine as raw 16-bit little-endian PCM."""
    samples = int(seconds * rate)
    return b"".join(
        struct.pack("<h", int(3000 * math.sin(2 * math.pi * 440 * i / rate)))
        for i in range(samples)
    )


@pytest.mark.skipif(find_ffmpeg() is None, reason="no ffmpeg binary installed")
def test_pcm_to_ogg_returns_a_real_ogg_stream() -> None:
    audio = pcm_to_ogg(_pcm())

    assert audio.startswith(b"OggS")
    assert len(audio) > 100


def test_pcm_to_ogg_rejects_empty_input() -> None:
    with pytest.raises(AudioTranscodeError):
        pcm_to_ogg(b"")


def test_pcm_to_ogg_reports_a_missing_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ffmpeg anywhere: a loud handled error, not a silent drop."""
    monkeypatch.setattr("telegram_documentaries.narrator_audio.find_ffmpeg", lambda: None)

    with pytest.raises(AudioTranscodeError, match="ffmpeg"):
        pcm_to_ogg(_pcm())


def test_mime_allowlist_covers_ogg_and_mp3() -> None:
    assert AUDIO_MIME_TYPES == {"ogg": "audio/ogg", "mp3": "audio/mpeg"}


def test_ffmpeg_prefers_path_over_bundled_binary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "telegram_documentaries.narrator_audio.shutil.which", lambda _: "/usr/bin/ffmpeg-fake"
    )
    assert find_ffmpeg() == "/usr/bin/ffmpeg-fake"


def test_ffmpeg_returns_none_when_nothing_is_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("telegram_documentaries.narrator_audio.shutil.which", lambda _: None)

    import builtins

    real_import = builtins.__import__

    def no_imageio_ffmpeg(name: str, *args: object, **kwargs: object) -> object:
        if name == "imageio_ffmpeg":
            raise ImportError("no imageio_ffmpeg")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_imageio_ffmpeg)

    assert find_ffmpeg() is None
