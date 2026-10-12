"""Offline tests for the direct Gemini TTS client's parsing/wrapping edge.

Reference: SPECS/2026-10-11-narrator/plan.md group 2.2, validation.md check 2.
Only the pure helpers that interpret the model's ``GenerateContentResponse``
are exercised here — no network, no ``GEMINI_API_KEY``, no real TTS call. The
live test (`test_narrator_live.py`) covers the real synthesis round-trip.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from telegram_documentaries.narrator import NarratorError
from telegram_documentaries.narrator_client import _extract_audio, _wrap_audio


def _inline(data: bytes, mime_type: str | None) -> Any:
    """A stand-in for one ``Part`` carrying inline audio data."""
    return SimpleNamespace(inline_data=SimpleNamespace(data=data, mime_type=mime_type))


def _response(*parts: Any) -> Any:
    """A stand-in ``GenerateContentResponse`` with a single candidate."""
    return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=list(parts)))])


# --- _extract_audio ----------------------------------------------------------


def test_extract_audio_returns_the_first_inline_payload() -> None:
    response = _response(_inline(b"\x01\x02pcm", "audio/L16;codec=pcm;rate=24000"))

    audio, mime_type = _extract_audio(response)

    assert audio == b"\x01\x02pcm"
    assert mime_type == "audio/L16;codec=pcm;rate=24000"


def test_extract_audio_skips_text_parts_and_empty_payloads() -> None:
    response = _response(
        SimpleNamespace(inline_data=None),
        _inline(b"", "audio/L16"),
        _inline(b"real-audio", "audio/ogg"),
    )

    audio, mime_type = _extract_audio(response)

    assert audio == b"real-audio"
    assert mime_type == "audio/ogg"


def test_extract_audio_without_inline_data_is_a_handled_error() -> None:
    with pytest.raises(NarratorError):
        _extract_audio(_response())


def test_extract_audio_handles_a_response_without_candidates() -> None:
    # `candidates` is `None` (the deadline/blocking case) — not an uncaught crash.
    with pytest.raises(NarratorError):
        _extract_audio(SimpleNamespace(candidates=None))


# --- _wrap_audio -------------------------------------------------------------


def test_wrap_audio_passes_through_bytes_that_already_start_with_oggs() -> None:
    result = _wrap_audio(b"OggS" + b"\x00" * 16, "application/octet-stream")

    assert result.format == "ogg"
    assert result.audio_bytes.startswith(b"OggS")


def test_wrap_audio_passes_through_a_declared_ogg_mime() -> None:
    result = _wrap_audio(b"not-magic-but-declared-ogg", "audio/ogg")

    assert result.format == "ogg"
    assert result.audio_bytes == b"not-magic-but-declared-ogg"


def test_wrap_audio_passes_through_an_mp3_mime() -> None:
    result = _wrap_audio(b"ID3\x00\x00audio", "audio/mpeg")

    assert result.format == "mp3"
    assert result.audio_bytes == b"ID3\x00\x00audio"


def test_wrap_audio_rejects_an_unexpected_mime() -> None:
    with pytest.raises(NarratorError):
        _wrap_audio(b"\x00\x00\x00\x00", "video/mp4")


def test_wrap_audio_turns_a_transcode_failure_into_a_handled_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Raw PCM with no encoder anywhere: a loud, handled NarratorError."""
    monkeypatch.setattr("telegram_documentaries.narrator_audio.find_ffmpeg", lambda: None)

    with pytest.raises(NarratorError):
        _wrap_audio(b"\x00\x01raw-pcm", "audio/L16;codec=pcm;rate=24000")
