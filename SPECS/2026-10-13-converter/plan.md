# The Converter — implementation plan (Phase 4)

Reference: `SPECS/2026-10-13-converter/requirements.md`.

## Group 1: Core types and parsing (offline, no ADK)

1.1 **Session schema bump** (`state.py`)
     - `SCHEMA_VERSION = 4`
     - Add `CONVERTING` to `Phase` enum

1.2 **Converter output contract** (`converter.py`)
     - `ConverterError(ValueError)` — handled error type
     - `ConverterOutput(BaseModel)` — `image_bytes: bytes` field only
     - `parse_output(raw: str) -> ConverterOutput` — JSON parse + schema validation:
       - Must be valid JSON object matching schema
       - `image_bytes` must be non-empty bytes
       - Any violation → `ConverterError`

1.3 **Dossier + photo context builder** (`converter.py`)
     - `converter_context(photo_bytes: bytes, dossier: Dossier) -> tuple[bytes, str]` — formats the dossier (profile, suggested_animal, Q&A) as text for the model prompt, and returns photo bytes + prompt text.

## Group 2: ADK client (offline-stubbable)

2.1 **Client protocol** (`converter.py`)
     - `ConverterClient(Protocol)` with `generate_image(photo_bytes: bytes, dossier_context: str) -> str` returning raw structured output for edge parsing.

2.2 **ADK-backed implementation** (`converter_client.py`)
     - `GeminiConverterClient` class:
       - `__init__(api_key: str, model: str = "gemini-3.1-flash-image")`
       - Builds one `LlmAgent` with:
         - `name="converter"`, `model=Gemini(model=..., client_kwargs={"api_key": api_key})`
         - `instruction=CONVERTER_INSTRUCTION` (see below)
         - `output_schema=ConverterOutput`
       - `InMemoryRunner` with `app_name="telegram_documentaries"`, `user_id="converter"`
       - `generate_image(photo_bytes: bytes, dossier_context: str) -> str` drives async runner with `asyncio.run`, same pattern as `interview_client.py`.
         - The photo bytes are passed as a `Part` with inline_data (mime_type="image/jpeg") to the agent.
         - The dossier context is passed as text content.

2.3 **Instruction constant** (`converter.py` or `converter_client.py`)
     - `CONVERTER_INSTRUCTION`: Wildlife documentary image generator persona. "You are creating a hybrid portrait for a nature documentary. Fuse the human subject's likeness with the animal archetype that best reflects their personality quirks from the dossier. Create a playful, believable wildlife-documentary-style image where the human's features merge with the animal's — e.g., a caffeinated badger with coffee-stained whiskers for a late-night coder, a meticulous beaver with a tiny clipboard for an organizer, a night-owl bat with oversized headphones for a night owl. The style is cinematic, detailed, and slightly humorous — like a BBC Earth frame with a wink."

## Group 3: Converter orchestrator (the stage)

3.1 **Converter class** (`converter.py`)
     - `__init__(state: StateDriver, client: ConverterClient, telegram: TelegramClient)`
     - `@log_call def generate_and_send(chat_id: int) -> ConverterOutput | None`:
       - Load session, assert phase is `CONVERTING`
       - Assert session has `photo` bytes and dossier has `profile` and `suggested_animal`
       - Build context via `converter_context(session.photo, session.dossier)`
       - Call `client.generate_image(photo_bytes, dossier_context)`
       - Parse via `parse_output`
       - Call `telegram.send_photo(chat_id, output.image_bytes)`
       - Advance `session.phase = Phase.SCRIPTING`
       - Save session
       - Return `output`

3.2 **Failure handling** (`converter.py`)
     - If any step fails (missing photo, missing dossier, client error, parse error, Telegram send error):
       - Log loudly (via `@log_call`)
       - Reply with `CONVERTER_FAILURE_TEXT` via `telegram.send_message(chat_id, CONVERTER_FAILURE_TEXT)`
       - Advance `session.phase = Phase.SCRIPTING` (pipeline continues per Narrator spec amendment)
       - Save session
       - Return `None`

3.3 **Error text constant** (`converter.py`)
     - `CONVERTER_FAILURE_TEXT`: in-character, cheeky, explicit that the portrait couldn't be made but the documentary continues. e.g., "The darkroom spirits were uncooperative today — no hybrid portrait emerged. But fear not! The narration and voice note will still find their way to you."

## Group 4: Bot wiring (integration)

4.1 **Bot imports and constants** (`bot.py`)
     - Import `Converter`, `CONVERTER_FAILURE_TEXT` from `converter`
     - Add `converter: Converter | None = None` to `Bot.__init__`

4.2 **Run Converter in bot** (`bot.py`)
     - Add `_run_converter(chat_id: int) -> None` method:
       - Call `self._converter.generate_and_send(chat_id)`
       - On success: image already sent by Converter, phase already advanced
       - On failure: Converter handles the failure text and phase advance internally

4.3 **Hook into text handler** (`bot.py`)
     - In `_handle_text`, after the Interviewer completes (phase becomes `CONVERTING`), call `_run_converter` in the same turn. The chat advances from `INTERVIEWING → CONVERTING → SCRIPTING` in sequence.

4.4 **Update Interviewer handoff** (`interviewer.py` / `bot.py`)
     - Ensure Interviewer advances phase to `CONVERTING` (not `SCRIPTING`) on completion
     - The Converter will then advance to `SCRIPTING`

## Group 5: Tests (Red/Green TDD)

5.1 **Unit tests** (`tests/test_converter.py`)
     - `parse_output` accepts valid JSON with `image_bytes`
     - `parse_output` rejects free text (not JSON)
     - `parse_output` rejects JSON missing `image_bytes` field
     - `parse_output` rejects `image_bytes` as non-bytes / empty
     - `Converter.generate_and_send` returns typed output for stubbed response
     - `Converter.generate_and_send` passes exact inputs to client
     - `Converter.generate_and_send` turns malformed model output into handled error (logged loudly)
     - `Converter.generate_and_send` on failure: sends failure text, advances to SCRIPTING, returns None

5.2 **Flow tests** (`tests/test_converter_flow.py`)
     - Complete flow: photo → interview → converter → image delivered, phase at SCRIPTING, dossier intact
     - Converter failure degrades gracefully, advances to SCRIPTING, dossier survives, Scripter/Narrator still run
     - Cross-chat isolation: two chats, independent conversions

5.3 **Live opt-in test** (`tests/test_converter_live.py`)
     - Real `gemini-3.1-flash-image` call when `GEMINI_API_KEY` set, skipped otherwise.

## Group 6: Constitution sync

6.1 Update `MISSION.md` if needed (Converter already described in pipeline).
6.2 Update `ROADMAP.md` Phase 4 status to "implemented and verified — see `SPECS/2026-10-13-converter/`.
6.3 Update `TECH.md` if any new patterns introduced (unlikely — follows existing Interviewer pattern).
6.4 Update `README.md` if new dependencies or run instructions change.

## Group 7: Verification

7.1 Run `scripts/test` — must pass (pytest + ruff + mypy).
7.2 Run validation checks from `validation.md`.