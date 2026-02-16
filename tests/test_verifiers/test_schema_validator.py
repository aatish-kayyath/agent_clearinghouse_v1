"""Unit tests for the SchemaVerifier.

Tests cover:
    - Valid JSON matching the schema -> pass
    - Valid JSON NOT matching the schema -> fail with errors
    - Invalid JSON (malformed string) -> fail
    - Missing schema -> fail
    - Invalid schema definition -> fail
"""

from __future__ import annotations

import pytest

from agentic_clearinghouse.domain.verifier_protocol import VerificationRequest
from agentic_clearinghouse.verifiers.schema_validator import SchemaVerifier

# --- Test fixtures ---

USER_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "age": {"type": "integer", "minimum": 0},
        "email": {"type": "string", "format": "email"},
    },
    "required": ["name", "age"],
}


def _make_request(payload: str, schema: dict | None = USER_SCHEMA) -> VerificationRequest:
    return VerificationRequest(
        contract_id="test-contract-001",
        payload=payload,
        verification_config={"type": "schema"},
        requirements_schema=schema,
    )


# --- Tests ---


class TestSchemaVerifierHappyPath:
    @pytest.mark.asyncio
    async def test_valid_json_passes(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request('{"name": "Alice", "age": 30}')
        result = await verifier.verify(request)

        assert result.is_valid is True
        assert result.score == 1.0
        assert "successfully validated" in result.details

    @pytest.mark.asyncio
    async def test_valid_json_with_optional_fields(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request(
            '{"name": "Bob", "age": 25, "email": "bob@example.com"}'
        )
        result = await verifier.verify(request)

        assert result.is_valid is True

    @pytest.mark.asyncio
    async def test_valid_json_with_extra_fields(self) -> None:
        """Extra fields are allowed by default in JSON Schema."""
        verifier = SchemaVerifier()
        request = _make_request(
            '{"name": "Charlie", "age": 40, "phone": "555-1234"}'
        )
        result = await verifier.verify(request)

        assert result.is_valid is True


class TestSchemaVerifierFailures:
    @pytest.mark.asyncio
    async def test_missing_required_field(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request('{"name": "Alice"}')  # missing "age"
        result = await verifier.verify(request)

        assert result.is_valid is False
        assert "1 error" in result.details
        errors = result.logs["validation_errors"]
        assert len(errors) == 1
        assert "age" in errors[0]["message"]

    @pytest.mark.asyncio
    async def test_wrong_type(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request('{"name": "Alice", "age": "thirty"}')
        result = await verifier.verify(request)

        assert result.is_valid is False
        assert result.logs["validation_errors"]

    @pytest.mark.asyncio
    async def test_negative_age(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request('{"name": "Alice", "age": -5}')
        result = await verifier.verify(request)

        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_multiple_errors(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request('{"age": "not_a_number"}')  # missing name + wrong type
        result = await verifier.verify(request)

        assert result.is_valid is False
        assert len(result.logs["validation_errors"]) >= 2


class TestSchemaVerifierEdgeCases:
    @pytest.mark.asyncio
    async def test_malformed_json(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request('{"name": "Alice", "age":}')  # invalid JSON
        result = await verifier.verify(request)

        assert result.is_valid is False
        assert result.error == "INVALID_JSON"

    @pytest.mark.asyncio
    async def test_empty_string_payload(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request("")
        result = await verifier.verify(request)

        assert result.is_valid is False
        assert result.error == "INVALID_JSON"

    @pytest.mark.asyncio
    async def test_missing_schema(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request('{"name": "Alice"}', schema=None)
        result = await verifier.verify(request)

        assert result.is_valid is False
        assert result.error == "MISSING_SCHEMA"

    @pytest.mark.asyncio
    async def test_array_payload_against_object_schema(self) -> None:
        verifier = SchemaVerifier()
        request = _make_request('[1, 2, 3]')
        result = await verifier.verify(request)

        assert result.is_valid is False
