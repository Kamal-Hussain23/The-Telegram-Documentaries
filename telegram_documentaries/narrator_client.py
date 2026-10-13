"""Direct Gemini TTS client used by the Narrator (Phase 6).

TECH.md: the Narrator is **plumbing, not an agent** — the Scripter's text goes
straight to Gemini TTS and back out as a voice note, with no conversational
turn. There is deliberately no ADK ``LlmAgent`` here: ``synthesize`` makes one
direct ``client.models.generate_content`` call against
``gemini-3.1-flash-tts-preview`` asking for ``AUDIO`` output.

The model's native audio payload is raw 16-bit PCM at 24 kHz (`audio/L16`).
Telegram voice notes need OGG/Opus (or MP3), so the raw PCM is wrapped via
``narrator_audio.pcm_to_ogg`` before the typed ``NarratorResult`` crosses back
into the core. If the model ever returns a pre-wrapped Telegram-compatible
stream (``audio/ogg`` / ``audio/mpeg``), it is passed through untouched.

Timeout configuration: ``DEFAULT_GEMINI_TIMEOUT = 60.0`` seconds. The
``timeout`` parameter wraps the ``generate_content`` call in
``asyncio.wait_for``; on timeout, ``NarratorError`` is raised.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor

from google import genai
from google.genai import types

from telegram_documentaries.narrator import NarratorError, NarratorResult
from telegram_documentaries.narrator_audio import AudioTranscodeError, pcm_to_ogg

NARRATOR_MODEL = "gemini-3.1-flash-tts-preview"
#: A prebuilt documentary-narrator voice (module constant so it is easy to
#: swap without code archaeology).
NARRATOR_VOICE = "Orus"
#: The Telegram-compatible container the raw PCM is wrapped into.
NARRATOR_AUDIO_FORMAT = "ogg"

#: The MIME type the TTS API reports for its raw PCM output.
PCM_MIME_TYPE = "audio/L16;codec=pcm;rate=24000"

#: Containers Telegram already understands — passed through without a transcode.
_OGG_MIME_TYPES = frozenset({"audio/ogg", "application/ogg"})
_MP3_MIME_TYPES = frozenset({"audio/mpeg", "audio/mp3", "audio/mpga"})

#: Default timeout for Gemini API calls (seconds).
DEFAULT_GEMINI_TIMEOUT = 60.0


class GeminiTTSClient:
    """Runs one direct TTS synthesis against ``gemini-3.1-flash-tts-preview``."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = NARRATOR_MODEL,
        voice: str = NARRATOR_VOICE,
        timeout: float = DEFAULT_GEMINI_TIMEOUT,
    ) -> None:
        if not api_key:
            raise ValueError("GEMINI_API_KEY must not be empty")
        self._model = model
        self._voice = voice
        self._timeout = timeout
        self._client = genai.Client(api_key=api_key)
        # ThreadPoolExecutor for running sync generate_content in async context
        self._executor = ThreadPoolExecutor(max_workers=1)

    def synthesize(self, text: str) -> NarratorResult:
        """Synthesise one narration script into a Telegram-compatible voice note.

        The full text travels in the request unchanged; the returned audio is
        wrapped (or passed through) before anything downstream sees it.
        """
        if not text or not text.strip():
            raise NarratorError("refusing to synthesise empty narration text")

        # Run the sync generate_content in a thread pool with asyncio.wait_for
        async def _run_with_timeout() -> types.GenerateContentResponse:
            loop = asyncio.get_running_loop()
            return await asyncio.wait_for(
                loop.run_in_executor(self._executor, self._sync_generate_content, text),
                timeout=self._timeout,
            )

        try:
            response = asyncio.run(_run_with_timeout())
        except TimeoutError as exc:
            raise NarratorError("TTS timeout") from exc

        audio, mime_type = _extract_audio(response)
        return _wrap_audio(audio, mime_type)

    def _sync_generate_content(self, text: str) -> types.GenerateContentResponse:
        """Synchronous wrapper for generate_content (runs in thread pool)."""
        return self._client.models.generate_content(
            model=self._model,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=self._voice),
                    ),
                ),
            ),
        )


def _extract_audio(response: types.GenerateContentResponse) -> tuple[bytes, str | None]:
    """The first inline audio payload in the response, plus its MIME type."""
    for candidate in response.candidates or []:
        content = candidate.content
        if content is None:
            continue
        for part in content.parts or []:
            inline = part.inline_data
            if inline is None:
                continue
            if inline.data:
                return inline.data, inline.mime_type
    raise NarratorError("TTS response contained no inline audio data")


def _wrap_audio(audio: bytes, mime_type: str | None) -> NarratorResult:
    """Put the model's audio into a Telegram-compatible container (or pass it through).

    Raw PCM (the model's native output — no MIME, ``audio/L16*``, or
    ``audio/pcm``) is wrapped into OGG/Opus. A payload that is already a
    Telegram-compatible stream is passed through untouched. Anything else is a
    handled ``NarratorError``.
    """
    if audio.startswith(b"OggS"):
        # Paranoia: never transcode audio that is already an OGG stream.
        return NarratorResult(audio_bytes=audio, format="ogg")

    normalized = (mime_type or "").lower()
    if mime_type is None or normalized.startswith("audio/l16") or normalized == "audio/pcm":
        try:
            return NarratorResult(audio_bytes=pcm_to_ogg(audio), format=NARRATOR_AUDIO_FORMAT)
        except AudioTranscodeError as exc:
            raise NarratorError(str(exc)) from exc
    if normalized in _OGG_MIME_TYPES:
        return NarratorResult(audio_bytes=audio, format="ogg")
    if normalized in _MP3_MIME_TYPES:
        return NarratorResult(audio_bytes=audio, format="mp3")
    raise NarratorError(f"unexpected TTS audio MIME type {mime_type!r}")
