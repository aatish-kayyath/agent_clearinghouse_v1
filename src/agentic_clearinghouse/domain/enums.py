"""Domain enumerations for the Agentic Clearinghouse.

These enums define the canonical states and types used throughout the system.
They are framework-agnostic (no SQLAlchemy, no FastAPI imports).
"""

import enum


class EscrowStatus(enum.StrEnum):
    """Lifecycle states of an escrow contract.

    State transitions are enforced by the EscrowStateMachine guard.
    See domain/state_machine.py for the transition table.
    """

    CREATED = "CREATED"
    FUNDED = "FUNDED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DISPUTED = "DISPUTED"


class EventType(enum.StrEnum):
    """Types of audit events recorded in the escrow_events table.

    Every state transition MUST produce exactly one event.
    This is the append-only forensic trail for disputes.
    """

    # Lifecycle events
    CONTRACT_CREATED = "CONTRACT_CREATED"
    CONTRACT_FUNDED = "CONTRACT_FUNDED"
    WORKER_ASSIGNED = "WORKER_ASSIGNED"
    WORK_SUBMITTED = "WORK_SUBMITTED"

    # Verification events
    VERIFICATION_STARTED = "VERIFICATION_STARTED"
    VERIFICATION_PASSED = "VERIFICATION_PASSED"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"

    # Settlement events
    PAYMENT_INITIATED = "PAYMENT_INITIATED"
    PAYMENT_CONFIRMED = "PAYMENT_CONFIRMED"

    # Dispute events
    DISPUTE_RAISED = "DISPUTE_RAISED"
    DISPUTE_RESOLVED_WORKER = "DISPUTE_RESOLVED_WORKER"
    DISPUTE_RESOLVED_BUYER = "DISPUTE_RESOLVED_BUYER"

    # Failure events
    CONTRACT_EXPIRED = "CONTRACT_EXPIRED"
    MAX_RETRIES_EXCEEDED = "MAX_RETRIES_EXCEEDED"


class VerifierType(enum.StrEnum):
    """Types of verification strategies available.

    Stored in escrow_contracts.verification_logic["type"].
    """

    CODE_EXECUTION = "code_execution"
    SEMANTIC = "semantic"
    SCHEMA = "schema"
