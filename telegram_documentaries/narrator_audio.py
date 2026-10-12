"""PCM → Telegram-compatible audio transcoding (raw model output → OGG/Opus).

The TTS model's native output is raw 16-bit little-endian PCM at 24 kHz, mono
(``audio/L16;codec=pcm;rate=24000``). Telegram voice notes must be OGG/Opus
(or MP3), so the raw payload is wrapped with ``ffmpeg`` before it ever reaches
``sendVoice``. The encoder is located by preferring a system ``ffmpeg`` on
PATH and falling back to the ``imageio-ffmpeg`` pip package's bundled binary
(a runtime dependency, so the bot works on machines without ffmpeg installed).
"""

from __future__ import annotations

import functools
import shutil
import subprocess

#: The TTS model's native output shape (16-bit LE PCM, mono, 24 kHz).
PCM_SAMPLE_RATE = 24000
PCM_CHANNELS = 1

#: Telegram-compatible containers and their MIME types. The Narrator stage
#: allows only these — a `format` value becomes a file extension, so it is
#: never a free string.
AUDIO_MIME_TYPES = {"ogg": "audio/ogg", "mp3": "audio/mpeg"}

#: Opus bitrate for a voice note: Telegram re-encodes anyway, 32 kbps is crisp
#: and keeps the note small.
OPUS_BITRATE = "32k"


class AudioTranscodeError(ValueError):
    """Raw TTS audio could not be wrapped into a Telegram-compatible container."""


@functools.lru_cache(maxsize=1)
def find_ffmpeg() -> str | None:
    """The path to a usable ffmpeg binary, or None when none exists.

    A system ``ffmpeg`` on PATH wins (predictable for deployments that manage
    it themselves); otherwise the binary bundled with the ``imageio-ffmpeg``
    package is used, so a fresh ``pip install`` is enough on any platform. The
    result is cached so repeated synthesis does not re-probe the filesystem.
    """
    system = shutil.which("ffmpeg")
    if system:
        return system
    try:
        import imageio_ffmpeg  # type: ignore[import-untyped]
    except ImportError:
        return None
    exe = imageio_ffmpeg.get_ffmpeg_exe()
    return str(exe) if exe else None


def pcm_to_ogg(pcm: bytes) -> bytes:
    """Wrap raw 16-bit LE PCM (24 kHz, mono) into an OGG/Opus stream.

    Pure stdin/stdout conversion — no intermediate files. A missing encoder,
    an ffmpeg failure, or a result that is not an OGG stream raises
    ``AudioTranscodeError`` (a handled, loudly-logged boundary error).
    """
    if not pcm:
        raise AudioTranscodeError("refusing to transcode empty PCM audio")

    exe = find_ffmpeg()
    if exe is None:
        raise AudioTranscodeError(
            "no ffmpeg binary available (checked PATH and imageio-ffmpeg); "
            "cannot wrap raw PCM audio into an OGG/Opus voice note"
        )

    command = [
        exe,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "s16le",
        "-ar",
        str(PCM_SAMPLE_RATE),
        "-ac",
        str(PCM_CHANNELS),
        "-i",
        "pipe:0",
        "-c:a",
        "libopus",
        "-b:a",
        OPUS_BITRATE,
        "-f",
        "ogg",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(command, input=pcm, capture_output=True, check=False)
    except OSError as exc:
        raise AudioTranscodeError(f"failed to run ffmpeg: {exc}") from exc

    if proc.returncode != 0:
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        raise AudioTranscodeError(f"ffmpeg failed to wrap PCM into OGG/Opus: {stderr.strip()}")
    if not proc.stdout.startswith(b"OggS"):
        raise AudioTranscodeError("ffmpeg produced output that is not an OGG stream")
    return proc.stdout
