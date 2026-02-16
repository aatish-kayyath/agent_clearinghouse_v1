"""Tests for domain enumerations."""

from __future__ import annotations

from agentic_clearinghouse.domain.enums import EscrowStatus, EventType, VerifierType


class TestEscrowStatus:
    def test_all_statuses_exist(self) -> None:
        expected = {
            "CREATED", "FUNDED", "IN_PROGRESS", "SUBMITTED",
            "VERIFYING", "COMPLETED", "FAILED", "DISPUTED",
        }
        actual = {s.value for s in EscrowStatus}
        assert actual == expected

    def test_status_is_str_enum(self) -> None:
        assert isinstance(EscrowStatus.CREATED, str)
        assert EscrowStatus.CREATED == "CREATED"


class TestEventType:
    def test_all_event_types_exist(self) -> None:
        # 4 lifecycle + 3 verification + 2 settlement + 3 dispute + 2 failure
        assert len(EventType) == 14

    def test_event_type_is_str_enum(self) -> None:
        assert isinstance(EventType.CONTRACT_CREATED, str)


class TestVerifierType:
    def test_verifier_types(self) -> None:
        assert VerifierType.CODE_EXECUTION == "code_execution"
        assert VerifierType.SEMANTIC == "semantic"
        assert VerifierType.SCHEMA == "schema"
