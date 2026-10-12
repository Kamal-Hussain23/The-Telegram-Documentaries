"""The Narrator stage: script → TTS audio → temp file → Telegram voice note.

Reference: SPECS/2026-10-11-narrator/requirements.md decisions,
plan.md groups 4.3–4.4, validation.md checks 2. Everything runs offline against
the stubbed TTS client and the stubbed ``send_voice``.
"""

from __future__ import annotations

import logging

import pytest
from telegram_documentaries.narrator import Narrator, NarratorError, NarratorResult
from telegram_documentaries.state import Phase, StateDriver
from tests.support.fakes import STUB_OGG, FakeTelegramClient, StubTTSClient

SCRIPT = (
    "In the vast kitchen of the universe, our subject, a midnight raccoon, "
    "prepares a humble midnight toast while the stars wheel overhead."
)

CHAT_ID = 42


def narrating_session(state: StateDriver, *, script: str = SCRIPT) -> None:
    """A chat parked in NARRATING with the Scripter's narration in the dossier."""
    session = state.load(CHAT_ID)
    session.phase = Phase.NARRATING
    session.dossier.script = script
    state.save(session)


def wired(tts: StubTTSClient, client: FakeTelegramClient) -> tuple[Narrator, StateDriver]:
    state = StateDriver()
    narrating_session(state)
    return Narrator(state, tts, client), state


# --- happy path (validation 2.1–2.4) -----------------------------------------


def test_passes_the_full_script_text_to_the_tts_client() -> None:
    """The exact `dossier.script` string travels in the TTS request, unchanged."""
    tts = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])
    narrator, _ = wired(tts, FakeTelegramClient())

    narrator.synthesize_and_deliver(CHAT_ID)

    assert tts.synthesize_calls == [SCRIPT]


def test_success_delivers_voice_note_advances_phase_and_clears_script(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audio persisted to a temp file, sent as an OGG voice note, phase advanced."""
    import telegram_documentaries.narrator as narrator_module

    monkeypatch.setattr(narrator_module, "_temporary_audio_dir", lambda: tmp_path)
    tts = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])
    client = FakeTelegramClient()
    narrator, state = wired(tts, client)

    narrator.synthesize_and_deliver(CHAT_ID)

    assert len(client.sent_voices) == 1
    chat_id, voice, mime_type, filename = client.sent_voices[0]
    assert chat_id == CHAT_ID
    assert voice == STUB_OGG
    assert mime_type == "audio/ogg"
    assert filename.startswith(f"narration_{CHAT_ID}_")
    assert filename.endswith(".ogg")

    session = state.load(CHAT_ID)
    assert session.phase is Phase.AWAITING_PHOTO
    assert session.dossier.script is None


def test_temporary_audio_file_is_removed_after_success(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No narration file leaks behind after a successful delivery."""
    import telegram_documentaries.narrator as narrator_module

    monkeypatch.setattr(narrator_module, "_temporary_audio_dir", lambda: tmp_path)
    tts = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])
    narrator, _ = wired(tts, FakeTelegramClient())

    narrator.synthesize_and_deliver(CHAT_ID)

    assert list(tmp_path.iterdir()) == []


def test_success_sends_mp3_passthrough_with_mpeg_mime(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An mp3-format result maps to audio/mpeg and an .mp3 filename."""
    import telegram_documentaries.narrator as narrator_module

    monkeypatch.setattr(narrator_module, "_temporary_audio_dir", lambda: tmp_path)
    mp3 = b"ID3" + b"\x00" * 32
    tts = StubTTSClient([NarratorResult(audio_bytes=mp3, format="mp3")])
    client = FakeTelegramClient()
    narrator, _ = wired(tts, client)

    narrator.synthesize_and_deliver(CHAT_ID)

    _, voice, mime_type, filename = client.sent_voices[0]
    assert voice == mp3
    assert mime_type == "audio/mpeg"
    assert filename.endswith(".mp3")


# --- preconditions (validation 2.5–2.8) --------------------------------------


def test_wrong_phase_is_a_handled_error() -> None:
    """Narrator refuses to run when the chat is not in NARRATING."""
    state = StateDriver()
    tts = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])
    client = FakeTelegramClient()
    narrator = Narrator(state, tts, client)

    with pytest.raises(NarratorError):
        narrator.synthesize_and_deliver(CHAT_ID)


def test_missing_script_is_a_handled_error() -> None:
    state = StateDriver()
    session = state.load(CHAT_ID)
    session.phase = Phase.NARRATING
    state.save(session)  # dossier.script stays None
    tts = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])
    narrator = Narrator(state, tts, FakeTelegramClient())

    with pytest.raises(NarratorError):
        narrator.synthesize_and_deliver(CHAT_ID)


def test_blank_script_is_a_handled_error() -> None:
    state = StateDriver()
    narrating_session(state, script="   \n ")
    tts = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])
    narrator = Narrator(state, tts, FakeTelegramClient())

    with pytest.raises(NarratorError):
        narrator.synthesize_and_deliver(CHAT_ID)
    assert tts.synthesize_calls == []


def test_empty_audio_is_a_handled_error() -> None:
    tts = StubTTSClient([NarratorResult(audio_bytes=b"", format="ogg")])
    client = FakeTelegramClient()
    narrator, _ = wired(tts, client)

    with pytest.raises(NarratorError):
        narrator.synthesize_and_deliver(CHAT_ID)

    assert client.sent_voices == []


def test_unsupported_audio_format_is_a_handled_error(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A free-form format string can never become a file extension."""
    import telegram_documentaries.narrator as narrator_module

    monkeypatch.setattr(narrator_module, "_temporary_audio_dir", lambda: tmp_path)
    tts = StubTTSClient([NarratorResult(audio_bytes=b"RIFF", format="../../wav")])
    narrator, state = wired(tts, FakeTelegramClient())

    with pytest.raises(NarratorError):
        narrator.synthesize_and_deliver(CHAT_ID)

    assert list(tmp_path.iterdir()) == []
    assert state.load(CHAT_ID).phase is Phase.NARRATING


# --- failure paths (validation 2.9–2.12) -------------------------------------


def test_tts_failure_is_logged_loudly_and_leaves_session_intact(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A raising TTS client: ERROR log, phase stays NARRATING, script survives."""
    tts = StubTTSClient([RuntimeError("gemini tts exploded")])
    client = FakeTelegramClient()
    narrator, state = wired(tts, client)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(NarratorError):
            narrator.synthesize_and_deliver(CHAT_ID)

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert client.sent_voices == []
    session = state.load(CHAT_ID)
    assert session.phase is Phase.NARRATING
    assert session.dossier.script == SCRIPT


def test_temp_dir_write_failure_is_logged_and_leaves_session_intact(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An unwritable scratch dir: handled error, nothing sent, NARRATING stays."""
    import telegram_documentaries.narrator as narrator_module

    blocker = tmp_path / "block"
    blocker.write_text("i am a file, not a directory")
    monkeypatch.setattr(narrator_module, "_temporary_audio_dir", lambda: blocker)
    tts = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])
    client = FakeTelegramClient()
    narrator, state = wired(tts, client)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(NarratorError):
            narrator.synthesize_and_deliver(CHAT_ID)

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert client.sent_voices == []
    assert state.load(CHAT_ID).phase is Phase.NARRATING
    assert state.load(CHAT_ID).dossier.script == SCRIPT


def test_voice_send_failure_cleans_up_temp_file_and_stays_in_narrating(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Telegram failing to accept the voice note: temp file still removed."""
    import telegram_documentaries.narrator as narrator_module

    monkeypatch.setattr(narrator_module, "_temporary_audio_dir", lambda: tmp_path)
    tts = StubTTSClient([NarratorResult(audio_bytes=STUB_OGG, format="ogg")])

    class FailingSendVoice(FakeTelegramClient):
        def send_voice(self, chat_id: int, voice: bytes, *, mime_type: str, filename: str) -> None:
            raise ConnectionError("telegram refused the voice note")

    client = FailingSendVoice()
    narrator, state = wired(tts, client)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(NarratorError):
            narrator.synthesize_and_deliver(CHAT_ID)

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert list(tmp_path.iterdir()) == []
    session = state.load(CHAT_ID)
    assert session.phase is Phase.NARRATING
    assert session.dossier.script == SCRIPT


# --- cross-chat isolation (validation 2.13) ----------------------------------


def test_two_chats_never_share_scripts_or_voice_notes(
    tmp_path: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Chat A's narration is A's alone; chat B is untouched."""
    import telegram_documentaries.narrator as narrator_module

    monkeypatch.setattr(narrator_module, "_temporary_audio_dir", lambda: tmp_path)
    script_two = "Behold the badger of the break room, guardian of the biscuit tin."
    audio_two = b"OggS" + b"B" * 64
    tts = StubTTSClient(
        [
            NarratorResult(audio_bytes=STUB_OGG, format="ogg"),
            NarratorResult(audio_bytes=audio_two, format="ogg"),
        ]
    )
    client = FakeTelegramClient()
    state = StateDriver()

    narrator = Narrator(state, tts, client)
    narrating_session(state)
    narrator.synthesize_and_deliver(CHAT_ID)

    # Chat B has never been touched, then narrates with its own script.
    untouched = state.load(99)
    assert untouched.phase is Phase.AWAITING_PHOTO
    assert untouched.dossier.script is None

    bearer_b = state.load(99)
    bearer_b.phase = Phase.NARRATING
    bearer_b.dossier.script = script_two
    state.save(bearer_b)
    narrator.synthesize_and_deliver(99)

    assert tts.synthesize_calls == [SCRIPT, script_two]
    voices = [voice for _, voice, _, _ in client.sent_voices]
    assert voices == [STUB_OGG, audio_two]
    assert state.load(99).phase is Phase.AWAITING_PHOTO
    assert len(list(tmp_path.iterdir())) == 0
