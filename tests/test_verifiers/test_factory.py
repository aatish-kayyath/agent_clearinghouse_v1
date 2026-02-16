"""Unit tests for the VerifierFactory."""

from __future__ import annotations

import pytest

from agentic_clearinghouse.verifiers import (
    CodeExecutionVerifier,
    SchemaVerifier,
    SemanticVerifier,
    VerifierFactory,
)


class TestVerifierFactory:
    def test_create_code_execution(self) -> None:
        verifier = VerifierFactory.create({"type": "code_execution"})
        assert isinstance(verifier, CodeExecutionVerifier)

    def test_create_semantic(self) -> None:
        verifier = VerifierFactory.create({"type": "semantic"})
        assert isinstance(verifier, SemanticVerifier)

    def test_create_schema(self) -> None:
        verifier = VerifierFactory.create({"type": "schema"})
        assert isinstance(verifier, SchemaVerifier)

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown verifier type"):
            VerifierFactory.create({"type": "quantum_entanglement"})

    def test_missing_type_raises(self) -> None:
        with pytest.raises(ValueError, match="must contain a 'type' key"):
            VerifierFactory.create({"timeout": 30})

    def test_empty_dict_raises(self) -> None:
        with pytest.raises(ValueError):
            VerifierFactory.create({})

    def test_get_supported_types(self) -> None:
        types = VerifierFactory.get_supported_types()
        assert "code_execution" in types
        assert "semantic" in types
        assert "schema" in types
        assert "mock" in types
        assert len(types) == 4
