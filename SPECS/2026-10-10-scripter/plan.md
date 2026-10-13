# The Scripter — implementation plan (Phase 5)

Reference: `SPECS/2026-10-10-scripter/requirements.md`.

## Group 1: Core types and parsing (offline, no ADK)

1.1 **Session schema bump** (`state.py`)
     - `SCHEMA_VERSION = 3`
     - Add `NARRATING` to `Phase` enum
     - Add `script: str | None = None` to `Dossier` model (persists the
       generated narration for the Narrator stage)

1.2 **Scripter output contract** (`scripter.py`)
     - `ScripterError(ValueError)` — handled error type
     - `ScripterOutput(BaseModel)` — `script: str` field only
     - `parse_output(raw: str) -> ScripterOutput` — JSON parse + schema
       validation + **constraint checks**:
       - Must be valid JSON object matching schema
       - `script` must be a single paragraph (no `

`)
       - `script` word count ≤ 90 (split on whitespace)
       - `script` must not contain markdown markers (`*`, `_`, `#`, ```, `~`, `[`, `]`, `(`, `)` used as formatting — conservative check)
       - Any violation → `ScripterError`

1.3 **Dossier context builder** (`scripter.py`)
     - `dossier_context(dossier: Dossier) -> str` — formats the completed
       dossier (profile, suggested_animal, Q&A) as text for the model prompt.

## Group 2: ADK client (offline-stubbable)

2.1 **Client protocol** (`scripter.py`)
     - `ScripterClient(Protocol)` with `generate_script(dossier_context: str) -> str` returning raw structured output for edge parsing.

2.2 **ADK-backed implementation** (`scripter_client.py`)
     - `GeminiScripterClient` class:
       - `__init__(api_key: str, model: str = "gemini-3.1-flash-lite")`
       - Builds one `LlmAgent` with:
         - `name="scripter"`, `model=Gemini(model=..., client_kwargs={"api_key": api_key})`
         - `instruction=SCRIPTER_INSTRUCTION` (see below)
         - `output_schema=ScripterOutput`
       - `InMemoryRunner` with `app_name="telegram_documentaries"`, `user_id="scripter"`
       - `generate_script(context: str) -> str` drives async runner with `asyncio.run`, same pattern as `interview_client.py`.

2.3 **Instruction constant** (`scripter.py` or `scripter_client.py`)
     - `SCRIPTER_INSTRUCTION`: Brian Cox physicist persona — wonder-struck cosmic narrator. Frames human quirks/bedtime/snacking as animal behaviours. "In the vast kitchen of the universe..." style. Output must be one paragraph, ≤90 words, no markdown, ready for voice synthesis.

## Group 3: Scripter orchestrator (the stage)

3.1 **Scripter class** (`scripter.py`)
     - `__init__(state: StateDriver, client: ScripterClient)`
     - `@log_call def generate(chat_id: int) -> ScripterOutput`:
       - Load session, assert phase is `SCRIPTING`
       - Assert dossier has `profile` and `suggested_animal`
       - Build context via `dossier_context(session.dossier)`
       - Call `client.generate_script(context)`
       - Parse via `parse_output`
       - Persist `output.script` to `session.dossier.script`
       - Advance `session.phase = Phase.NARRATING`
       - Save session
       - Return `output`

## Group 4: Bot wiring (integration)

4.1 **Bot imports and constants** (`bot.py`)
     - Import `Scripter`, `SCRIPTING_FAILURE_TEXT` from `scripter`
     - Add `scripter: Scripter | None = None` to `Bot.__init__`

4.2 **Run Scripter in bot** (`bot.py`)
     - Add `_run_scripter(chat_id: int) -> None` method:
       - Call `self._scripter.generate(chat_id)`
       - On success: `self._client.send_message(chat_id, output.script)`
       - On failure: log loudly, reset phase to `SCRIPTING`, send `SCRIPTING_FAILURE_TEXT`

4.3 **Hook into text handler** (`bot.py`)
     - In `_handle_text`, after the interview completes, call `_run_scripter` in the same turn. The chat advances directly from `INTERVIEWING` to `SCRIPTING`, skipping the Converter stage entirely.

4.4 **Error text constant** (`scripter.py`)
     - `SCRIPTING_FAILURE_TEXT`: in-character, cheeky, explicit that the dossier is safe and we can retry.

## Group 5: Tests (Red/Green TDD)

5.1 **Unit tests** (`tests/test_scripter.py`)
     - `parse_output` accepts valid JSON
     - `parse_output` rejects free text
     - `parse_output` rejects schema violations
     - `parse_output` rejects multi-paragraph output
     - `parse_output` rejects >90 words
     - `parse_output` rejects markdown formatting
     - `Scripter.generate` returns typed output for stubbed response
     - `Scripter.generate` passes exact inputs to client
     - `Scripter.generate` turns malformed model output into handled error (logged loudly)

5.2 **Flow tests** (`tests/test_scripter_flow.py`)
     - Complete flow: photo → interview → scripter → script delivered, phase at NARRATING, script persisted
     - Scripter failure degrades gracefully, stays in SCRIPTING, dossier survives, retry works
     - Cross-chat isolation: two chats, independent scripts

5.3 **Live opt-in test** (`tests/test_scripter_live.py`)
     - Real `gemini-3.1-flash-lite` call when `GEMINI_API_KEY` set, skipped otherwise.

## Group 6: Constitution sync

6.1 Update `MISSION.md` if needed (no changes expected — Scripter is already described in the pipeline).
6.2 Update `ROADMAP.md` Phase 5 status to "implemented and verified — see `SPECS/2026-10-10-scripter/`.
6.3 Update `TECH.md` if any new patterns introduced (unlikely — follows existing Interviewer pattern).
6.4 Update `README.md` if new dependencies or run instructions change.

## Group 7: Verification

7.1 Run `scripts/test` — must pass (pytest + ruff + mypy).
7.2 Run validation checks from `validation.md`.
