"""Domain layer — pure business logic with zero framework dependencies."""

from agentic_clearinghouse.domain.enums import (
    EscrowStatus,
    EventType,
    VerifierType,
)
from agentic_clearinghouse.domain.exceptions import (
    ClearinghouseError,
    ContractNotFoundError,
    InvalidStateTransitionError,
)
from agentic_clearinghouse.domain.state_machine import (
    EscrowStateMachine,
    validate_transition,
)
from agentic_clearinghouse.domain.verifier_protocol import (
    VerificationRequest,
    VerificationResult,
    VerifierStrategy,
)

__all__ = [
    "EscrowStatus",
    "EventType",
    "VerifierType",
    "ClearinghouseError",
    "ContractNotFoundError",
    "InvalidStateTransitionError",
    "EscrowStateMachine",
    "validate_transition",
    "VerificationRequest",
    "VerificationResult",
    "VerifierStrategy",
]
