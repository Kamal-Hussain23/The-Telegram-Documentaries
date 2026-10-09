# MISSION.md — The Telegram Documentaries

## Vision

A Telegram bot that turns a portrait photo into a narrated comedy wildlife
documentary about you. The user sends a photo of themselves and, a couple of
minutes later, receives three things: a hybrid animal version of themselves, a
dramatic one-paragraph narration of that creature's life, and a voice note
reading the narration aloud.

The comedy comes from sincerity — the bot treats every subject as a majestic,
rare animal being observed in the wild.

## The end-to-end experience

1. User opens a DM and sends `/start`.
2. User sends a portrait photo.
3. **The Bouncer** (Gemini 3.1 Flash Lite vision gate) confirms a human is
   present. Non-human images get a cheeky in-character rejection and a state
   reset.
4. **The Interviewer** (Gemini 3.1 Flash Lite, the orchestrator) asks 3–4
   questions, one at a time, accumulating a behavioural dossier keyed to the
   user's `chat_id`, and outputs a suggested animal.
5. **The Converter** (Gemini 3.1 Flash Image) fuses the original photo with the
   dossier into a hybrid animal portrait, returned directly to Telegram with no
   intermediate text hop.
6. **The Scripter** (Gemini 3.1 Flash Lite) writes one paragraph (~60–90 words)
   of dramatic British wildlife-documentary narration built from the dossier.
7. **The Narrator** (not an agent — a direct hop to Gemini TTS,
   `gemini-3.1-flash-tts-preview`) renders the script to a Telegram-compatible
   audio format (OGG/MP3) and the bot sends it as a voice note.

## In scope

- Exactly the five pipeline stages above.
- Telegram **long polling** transport (no webhooks, no public URL).
- In-memory session state keyed by `chat_id`.
- Secrets read from `.env` (`TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`).
- `/start` and `/restart` resetting the session and purging temporary media.

## Out of scope

Explicitly **not** part of this project (YAGNI — do not build, configure, or
leave room for these):

- **Webhooks / public URLs.** Long polling only; never expose a port.
- **Database persistence.** State lives in process memory. A process restart
  wipes all sessions, and that is acceptable.
- **Group-chat usage.** The bot is used in 1:1 DMs only; group messages are
  ignored.
- **Video output and audio input.** Outputs are text, one image, and one voice
  note. No video generation, no voice messages or audio transcription.
- **Multi-language support.** English only.
- **User accounts.** Identity is Telegram's `chat_id` and nothing more.

## Success criteria

- **Happy path:** the full journey from `/start` to voice note completes
  without manual intervention.
- **Reset:** `/start` and `/restart` purge session state *and* temporary media
  files without restarting the process, and the conversation can begin again
  immediately.
- **Graceful degradation:** text arriving during the photo stage, a second photo
  during the interview, or any wrong payload at any stage produces a friendly,
  in-character reply — never a crash, stack trace, or silent drop.

## Non-negotiables

- **No cross-user leakage.** One user's session, photo, dossier, or narration
  must never appear in another user's chat.
- **No hardcoded secrets.** Tokens and API keys live only in `.env`, which is
  gitignored. Never in source, tests, or documentation.
