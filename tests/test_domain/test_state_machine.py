"""Tests for the EscrowStateMachine domain guard.

These tests verify that:
    1. All valid transitions are allowed.
    2. All invalid transitions are blocked.
    3. The convenience function validate_transition works.
    4. Edge cases (disputes, retries) behave correctly.
"""

from __future__ import annotations

import pytest
from statemachine.exceptions import TransitionNotAllowed

from agentic_clearinghouse.domain.state_machine import (
    EscrowStateMachine,
    validate_transition,
)


class TestHappyPath:
    """Test the full happy-path lifecycle: CREATED -> COMPLETED."""

    def test_full_lifecycle(self) -> None:
        sm = EscrowStateMachine("CREATED")
        assert sm.status == "CREATED"

        sm.on_chain_confirmed()
        assert sm.status == "FUNDED"

        sm.worker_accepts()
        assert sm.status == "IN_PROGRESS"

        sm.worker_submits()
        assert sm.status == "SUBMITTED"

        sm.auto_verify()
        assert sm.status == "VERIFYING"

        sm.verification_passed()
        assert sm.status == "COMPLETED"


class TestRetryPath:
    """Test the retry flow: VERIFYING -> IN_PROGRESS -> ... -> VERIFYING."""

    def test_verification_failed_retry(self) -> None:
        sm = EscrowStateMachine("VERIFYING")
        sm.verification_failed_retry()
        assert sm.status == "IN_PROGRESS"

        # Can submit again
        sm.worker_submits()
        assert sm.status == "SUBMITTED"

        sm.auto_verify()
        assert sm.status == "VERIFYING"

    def test_max_retries_exceeded(self) -> None:
        sm = EscrowStateMachine("VERIFYING")
        sm.max_retries_exceeded()
        assert sm.status == "FAILED"


class TestDisputePath:
    """Test dispute transitions."""

    def test_dispute_from_funded(self) -> None:
        sm = EscrowStateMachine("FUNDED")
        sm.buyer_disputes()
        assert sm.status == "DISPUTED"

    def test_dispute_from_in_progress(self) -> None:
        sm = EscrowStateMachine("IN_PROGRESS")
        sm.buyer_disputes()
        assert sm.status == "DISPUTED"

    def test_dispute_resolved_for_worker(self) -> None:
        sm = EscrowStateMachine("DISPUTED")
        sm.dispute_resolved_for_worker()
        assert sm.status == "COMPLETED"

    def test_dispute_resolved_for_buyer(self) -> None:
        sm = EscrowStateMachine("DISPUTED")
        sm.dispute_resolved_for_buyer()
        assert sm.status == "FAILED"


class TestTimeoutPath:
    """Test timeout transitions."""

    def test_created_timeout(self) -> None:
        sm = EscrowStateMachine("CREATED")
        sm.timeout_expired()
        assert sm.status == "FAILED"


class TestIllegalTransitions:
    """Verify that illegal transitions raise TransitionNotAllowed."""

    def test_created_to_completed(self) -> None:
        sm = EscrowStateMachine("CREATED")
        with pytest.raises(TransitionNotAllowed):
            sm.verification_passed()

    def test_funded_to_submitted(self) -> None:
        sm = EscrowStateMachine("FUNDED")
        with pytest.raises(TransitionNotAllowed):
            sm.worker_submits()

    def test_completed_is_final(self) -> None:
        sm = EscrowStateMachine("COMPLETED")
        assert sm.get_allowed_events() == []

    def test_failed_is_final(self) -> None:
        sm = EscrowStateMachine("FAILED")
        assert sm.get_allowed_events() == []


class TestAllowedEvents:
    """Test the get_allowed_events helper."""

    def test_created_allowed(self) -> None:
        sm = EscrowStateMachine("CREATED")
        allowed = sm.get_allowed_events()
        assert "on_chain_confirmed" in allowed
        assert "timeout_expired" in allowed
        assert len(allowed) == 2

    def test_funded_allowed(self) -> None:
        sm = EscrowStateMachine("FUNDED")
        allowed = sm.get_allowed_events()
        assert "worker_accepts" in allowed
        assert "buyer_disputes" in allowed

    def test_verifying_allowed(self) -> None:
        sm = EscrowStateMachine("VERIFYING")
        allowed = sm.get_allowed_events()
        assert "verification_passed" in allowed
        assert "verification_failed_retry" in allowed
        assert "max_retries_exceeded" in allowed


class TestValidateTransitionFunction:
    """Test the convenience function."""

    def test_valid_transition(self) -> None:
        result = validate_transition("FUNDED", "worker_accepts")
        assert result == "IN_PROGRESS"

    def test_invalid_event_name(self) -> None:
        with pytest.raises(ValueError, match="Unknown event"):
            validate_transition("FUNDED", "nonexistent_event")

    def test_invalid_status(self) -> None:
        with pytest.raises(ValueError, match="Unknown status"):
            EscrowStateMachine("INVALID_STATUS")
