# The Telegram Documentaries

A Telegram bot that turns your portrait photo into a narrated comedy wildlife
documentary about you. Send a photo, answer a few questions, and receive a
hybrid animal portrait of yourself, a dramatic paragraph about its life, and a
voice note reading it aloud.

Built with Python and Google's Agent Development Kit (ADK), talking to Telegram
over **long polling** — no webhooks, no public URL, no extra infrastructure.

## The pipeline

| Stage | Model | What it does |
| --- | --- | --- |
| **The Bouncer** | Gemini 3.1 Flash Lite (vision) | Confirms a human is in the photo; cheekily rejects anything else and resets the session. |
| **The Interviewer** | Gemini 3.1 Flash Lite | The orchestrator. Asks 5–7 questions one at a time, builds a behavioural dossier, and suggests an animal. |
| **The Converter** | Gemini 3.1 Flash Image | Fuses your photo and dossier into a hybrid animal portrait, sent straight back to the chat. |
| **The Scripter** | Gemini 3.1 Flash Lite | Writes one paragraph (~60–90 words) of dramatic British wildlife narration. |
| **The Narrator** | Gemini TTS | Not an agent — the script goes directly to text-to-speech and comes back as a voice note. |

Session state is held in memory, keyed by your Telegram `chat_id`. `/start` and
`/restart` clear it and remove any temporary files without restarting the bot.

## Requirements

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A Google Gemini API key

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Copy the example environment file and fill in your secrets:

   ```bash
   cp .env.example .env
   ```

   ```
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   GEMINI_API_KEY=your_gemini_api_key_here
   ```

   `.env` is gitignored. Never put real keys in `.env.example`, source, or
   docs.

3. Run the bot:

   ```bash
   python -m <package>
   ```

   It polls Telegram outbound over HTTPS, so it works behind NAT and firewalls
   with no ports opened.

## Development

Two scripts are the ground truth for this repo. They are created in Phase 1 of
the roadmap:

- **`scripts/test`** — runs the full check suite: `pytest`, `ruff check`, and
  `mypy`. Run this before you consider any change done.
- **`scripts/hooks`** — the pre-commit checks, using the same tooling and
  configuration.

Tests are written **before** the code (Red/Green TDD). A phase from the
roadmap is complete only when its acceptance criteria are verified with these
scripts green.

## Project constitution

The contract this project is built against lives in `SPECS/`:

- [`SPECS/MISSION.md`](SPECS/MISSION.md) — what the product is, and what it
  explicitly is not.
- [`SPECS/TECH.md`](SPECS/TECH.md) — stack, architecture, and engineering
  policies.
- [`SPECS/ROADMAP.md`](SPECS/ROADMAP.md) — the ordered phase plan.

Feature specs live alongside them as `SPECS/<YYYY-MM-DD>-<feature-name>/`.

## Status

Early development. See [`SPECS/ROADMAP.md`](SPECS/ROADMAP.md) for what's built
and what's next.
