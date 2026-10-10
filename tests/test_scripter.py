"""The Scripter's model output is a typed contract, never free text.

Reference: SPECS/2026-10-10-scripter/requirements.md decisions 3, 4, 7, 8, 9,
plan.md groups 1.2–1.3 and 3.1, validation.md checks 2.
"""

from __future__ import annotations

import logging

import pytest
from telegram_documentaries.scripter import (
    SCRIPTER_INSTRUCTION,
    Scripter,
    ScripterError,
    ScripterOutput,
    dossier_context,
    parse_output,
)
from telegram_documentaries.state import Dossier, Phase, StateDriver
from tests.support.fakes import StubScripterClient, scripter_output_json

# --- parse_output contract (plan 1.2) ----------------------------------------


def test_parse_output_accepts_valid_json() -> None:
    """Valid JSON with script field is accepted and typed."""
    script = "In the vast kitchen of the universe, the subject prepares a midnight toast."
    raw = scripter_output_json(script)
    output = parse_output(raw)

    assert isinstance(output, ScripterOutput)
    assert output.script == script


def test_parse_output_rejects_free_text() -> None:
    """Non-JSON free text is rejected."""
    with pytest.raises(ScripterError):
        parse_output("Here is your script: the subject is a raccoon.")


@pytest.mark.parametrize(
    "raw",
    [
        "{not json}",
        '["script"]',
        "{}",
        '{"profile": "missing script field"}',
        '{"script": 123}',
        '{"script": ["not", "a", "string"]}',
    ],
)
def test_parse_output_rejects_schema_violations(raw: str) -> None:
    """JSON not matching ScripterOutput schema is rejected."""
    with pytest.raises(ScripterError):
        parse_output(raw)


def test_parse_output_rejects_multi_paragraph() -> None:
    """Output containing double newline (multi-paragraph) is rejected."""
    raw = scripter_output_json("Paragraph one.\n\nParagraph two.")
    with pytest.raises(ScripterError):
        parse_output(raw)


@pytest.mark.parametrize(
    "separator",
    [
        "\n\n",
        "\r\n\r\n",
        "\r\r",
        "\u2028\u2028",
        "\u2029\u2029",
    ],
)
def test_parse_output_treats_carriage_and_unicode_separators_as_paragraph_breaks(
    separator: str,
) -> None:
    """Windows and unicode paragraph separators count as paragraph breaks."""
    raw = scripter_output_json(f"Paragraph one.{separator}Paragraph two.")
    with pytest.raises(ScripterError):
        parse_output(raw)


def test_parse_output_rejects_empty_script() -> None:
    """An empty script is not a valid narration."""
    with pytest.raises(ScripterError):
        parse_output(scripter_output_json(""))


@pytest.mark.parametrize("blank", ["   ", "\t", "\n", " \t\n "])
def test_parse_output_rejects_whitespace_only_script(blank: str) -> None:
    """A whitespace-only script is not a valid narration."""
    with pytest.raises(ScripterError):
        parse_output(scripter_output_json(blank))


def test_parse_output_rejects_over_90_words() -> None:
    """Output exceeding 90 words is rejected."""
    long_script = " ".join([f"word{i}" for i in range(95)])  # 95 words
    raw = scripter_output_json(long_script)
    with pytest.raises(ScripterError):
        parse_output(raw)


@pytest.mark.parametrize(
    "markdown_script",
    [
        "The subject *italic* in the kitchen.",
        "The subject **bold** in the kitchen.",
        "The subject _italic_ in the kitchen.",
        "The subject __bold__ in the kitchen.",
        "# Heading",
        "The subject ```code``` in the kitchen.",
        "The subject ~~strikethrough~~ in the kitchen.",
        "The subject [link](url) in the kitchen.",
        "The subject `inline code` in the kitchen.",
    ],
)
def test_parse_output_rejects_markdown_formatting(markdown_script: str) -> None:
    """Output containing a markdown construct is rejected."""
    raw = scripter_output_json(markdown_script)
    with pytest.raises(ScripterError):
        parse_output(raw)


@pytest.mark.parametrize(
    "script",
    [
        "The subject (a curious raccoon) toasts a bagel.",
        "He hides [secret] snacks behind the kettle.",
        "Roughly ~90 words of wonder later, the toast appears.",
        "It's the subject's favourite, well-organised ritual.",
        "The stars wheel overhead... and the toast waits.",
        "The kitchen cools to precisely 3.14 degrees.",
    ],
)
def test_parse_output_accepts_ordinary_prose_punctuation(script: str) -> None:
    """Prose punctuation — () [] a single ~ ' - ... decimals — is not markdown."""
    output = parse_output(scripter_output_json(script))
    assert output.script == script


def test_parse_output_accepts_exactly_90_words() -> None:
    """Exactly 90 words is accepted (boundary)."""
    script = " ".join([f"word{i}" for i in range(90)])
    raw = scripter_output_json(script)
    output = parse_output(raw)
    assert output.script == script


def test_parse_output_accepts_single_paragraph_with_single_newlines() -> None:
    """Single paragraph with single newlines (but not double) is accepted."""
    raw = scripter_output_json("Line one.\nLine two.\nLine three.")
    output = parse_output(raw)
    assert output.script == "Line one.\nLine two.\nLine three."


# --- dossier_context (plan 1.3) ----------------------------------------------


def test_dossier_context_formats_complete_dossier() -> None:
    """dossier_context produces expected text format for completed dossier."""
    dossier = Dossier(
        questions=[
            "What do you do at midnight?",
            "What is your favourite snack?",
        ],
        answers=[
            "I scroll through star charts.",
            "Dark chocolate, always.",
        ],
        profile="A nocturnal stargazer with a chocolate habit.",
        suggested_animal="owl",
    )
    context = dossier_context(dossier)

    assert "Profile: A nocturnal stargazer with a chocolate habit." in context
    assert "Suggested animal: owl" in context
    assert "Question 1: What do you do at midnight?" in context
    assert "Answer 1: I scroll through star charts." in context
    assert "Question 2: What is your favourite snack?" in context
    assert "Answer 2: Dark chocolate, always." in context


# --- Scripter orchestrator (plan 3.1) ----------------------------------------


def test_scripter_returns_typed_output_for_stubbed_response() -> None:
    """Scripter.generate returns typed ScripterOutput for stubbed client."""
    state = StateDriver()
    client = StubScripterClient(
        [scripter_output_json("In the vast kitchen, the subject prepares toast.")]
    )
    scripter = Scripter(state, client)

    # Set up session at SCRIPTING phase with completed dossier
    session = state.load(42)
    session.phase = Phase.SCRIPTING
    session.dossier = Dossier(
        profile="A midnight snacker.",
        suggested_animal="raccoon",
        questions=["What do you eat at midnight?"],
        answers=["Toast with jam."],
    )
    state.save(session)

    output = scripter.generate(42)

    assert isinstance(output, ScripterOutput)
    assert output.script == "In the vast kitchen, the subject prepares toast."
    # Phase advanced to NARRATING
    assert state.load(42).phase is Phase.NARRATING
    # Script persisted in dossier
    assert state.load(42).dossier.script == "In the vast kitchen, the subject prepares toast."


def test_scripter_passes_exact_dossier_context_to_client() -> None:
    """Scripter passes the exact dossier context to the client."""
    state = StateDriver()
    client = StubScripterClient([scripter_output_json("The subject prepares toast.")])
    scripter = Scripter(state, client)

    session = state.load(42)
    session.phase = Phase.SCRIPTING
    session.dossier = Dossier(
        profile="A midnight snacker.",
        suggested_animal="raccoon",
        questions=["What do you eat at midnight?"],
        answers=["Toast with jam."],
    )
    state.save(session)

    scripter.generate(42)

    expected_context = (
        "Profile: A midnight snacker.\n"
        "Suggested animal: raccoon\n"
        "Interview:\n"
        "  Question 1: What do you eat at midnight?\n"
        "  Answer 1: Toast with jam."
    )
    assert client.generate_calls == [expected_context]


def test_scripter_turns_malformed_model_output_into_handled_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Malformed model output raises ScripterError, logged at ERROR level."""
    state = StateDriver()
    client = StubScripterClient(["I am not sure, maybe a script about toast?"])
    scripter = Scripter(state, client)

    session = state.load(42)
    session.phase = Phase.SCRIPTING
    session.dossier = Dossier(
        profile="A midnight snacker.",
        suggested_animal="raccoon",
        questions=["What do you eat?"],
        answers=["Toast."],
    )
    state.save(session)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ScripterError):
            scripter.generate(42)

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    # Phase stays SCRIPTING on failure
    assert state.load(42).phase is Phase.SCRIPTING


def test_scripter_requires_scripting_phase() -> None:
    """Scripter fails if session is not in SCRIPTING phase."""
    state = StateDriver()
    client = StubScripterClient([scripter_output_json("A script.")])
    scripter = Scripter(state, client)

    session = state.load(42)
    session.phase = Phase.INTERVIEWING  # wrong phase
    session.dossier = Dossier(
        profile="A midnight snacker.",
        suggested_animal="raccoon",
    )
    state.save(session)

    with pytest.raises(ScripterError):
        scripter.generate(42)


def test_scripter_requires_completed_dossier() -> None:
    """Scripter fails if dossier is incomplete (missing profile or animal)."""
    state = StateDriver()
    client = StubScripterClient([scripter_output_json("A script.")])
    scripter = Scripter(state, client)

    # Missing profile
    session = state.load(42)
    session.phase = Phase.SCRIPTING
    session.dossier = Dossier(suggested_animal="raccoon")
    state.save(session)

    with pytest.raises(ScripterError):
        scripter.generate(42)

    # Missing suggested_animal
    session = state.load(43)
    session.phase = Phase.SCRIPTING
    session.dossier = Dossier(profile="A snacker.")
    state.save(session)

    with pytest.raises(ScripterError):
        scripter.generate(43)


def test_scripter_error_is_a_value_error() -> None:
    """ScripterError is a ValueError subtype for caught handling."""
    assert issubclass(ScripterError, ValueError)


# --- SCRIPTER_INSTRUCTION presence --------------------------------------------


def test_scripter_instruction_exists_and_mentions_brian_cox() -> None:
    """The instruction constant exists and mentions the Brian Cox persona."""
    assert "Brian Cox" in SCRIPTER_INSTRUCTION
    assert "physicist" in SCRIPTER_INSTRUCTION.lower()
    assert "90" in SCRIPTER_INSTRUCTION  # word limit mentioned
    lower = SCRIPTER_INSTRUCTION.lower()
    assert "markdown" in lower or "formatting" in lower
