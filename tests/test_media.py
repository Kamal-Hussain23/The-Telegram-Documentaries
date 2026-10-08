"""Downloaded bytes are untrusted: size, type, and shape validated at the edge.

Reference: SPECS/2026-10-06-bouncer/plan.md group 1.7 and 2.3,
validation.md check 3.1.
"""

from __future__ import annotations

import logging

import pytest
from telegram_documentaries.client import (
    MAX_IMAGE_BYTES,
    ImageValidationError,
    validate_image,
)
from tests.support.fakes import fixture_bytes


def test_accepts_a_jpeg_with_a_matching_content_type() -> None:
    validate_image(fixture_bytes("person.jpg"), "image/jpeg")


def test_rejects_an_oversize_payload() -> None:
    oversize = b"\xff\xd8\xff" + b"\x00" * MAX_IMAGE_BYTES

    with pytest.raises(ImageValidationError):
        validate_image(oversize, "image/jpeg")


def test_rejects_a_wrong_content_type() -> None:
    with pytest.raises(ImageValidationError):
        validate_image(fixture_bytes("person.jpg"), "application/pdf")


def test_rejects_an_absent_content_type() -> None:
    with pytest.raises(ImageValidationError):
        validate_image(fixture_bytes("person.jpg"), None)


def test_rejects_a_non_image_payload() -> None:
    with pytest.raises(ImageValidationError):
        validate_image(b"this is definitely not an image", "image/jpeg")


def test_rejects_an_empty_payload() -> None:
    with pytest.raises(ImageValidationError):
        validate_image(b"", "image/jpeg")


def test_invalid_payload_is_logged_loudly(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        with pytest.raises(ImageValidationError):
            validate_image(b"nope", "image/jpeg")

    assert any(record.levelno >= logging.ERROR for record in caplog.records)
