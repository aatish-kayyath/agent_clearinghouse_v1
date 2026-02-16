"""Escrow Contract State Machine Guard.

Uses python-statemachine to enforce legal state transitions at the domain level.
This is the "trust code" layer — no matter what LangGraph or the API does,
an illegal transition (e.g., CREATED -> COMPLETED) will raise TransitionNotAllowed.

The state machine is instantiated per-contract and validates transitions before
the ORM model's status field is updated.

Transition table:
    CREATED       -> FUNDED           (on_chain_confirmed)
    CREATED       -> FAILED           (timeout_expired)
    FUNDED        -> IN_PROGRESS      (worker_accepts)
    FUNDED        -> DISPUTED         (buyer_disputes)
    IN_PROGRESS   -> SUBMITTED        (worker_submits)
    IN_PROGRESS   -> DISPUTED         (buyer_disputes)
    SUBMITTED     -> VERIFYING        (auto_verify)
    VERIFYING     -> COMPLETED        (verification_passed)
    VERIFYING     -> IN_PROGRESS      (verification_failed_retry)
    VERIFYING     -> FAILED           (max_retries_exceeded)
    DISPUTED      -> COMPLETED        (dispute_resolved_for_worker)
    DISPUTED      -> FAILED           (dispute_resolved_for_buyer)
"""

from __future__ import annotations

from statemachine import State, StateMachine


class EscrowStateMachine(StateMachine):
    """State machine that guards escrow contract lifecycle transitions.

    Usage:
        sm = EscrowStateMachine(current_status="FUNDED")
        sm.worker_accepts()  # transitions to IN_PROGRESS
        sm.current_state     # State('IN_PROGRESS', ...)
    """

    # --- States ---
    CREATED = State("CREATED", initial=True)
    FUNDED = State("FUNDED")
    IN_PROGRESS = State("IN_PROGRESS")
    SUBMITTED = State("SUBMITTED")
    VERIFYING = State("VERIFYING")
    COMPLETED = State("COMPLETED", final=True)
    FAILED = State("FAILED", final=True)
    DISPUTED = State("DISPUTED")

    # --- Events / Transitions ---

    # Funding
    on_chain_confirmed = CREATED.to(FUNDED)
    timeout_expired = CREATED.to(FAILED)

    # Worker assignment
    worker_accepts = FUNDED.to(IN_PROGRESS)

    # Work submission
    worker_submits = IN_PROGRESS.to(SUBMITTED)

    # Verification trigger
    auto_verify = SUBMITTED.to(VERIFYING)

    # Verification outcomes
    verification_passed = VERIFYING.to(COMPLETED)
    verification_failed_retry = VERIFYING.to(IN_PROGRESS)
    max_retries_exceeded = VERIFYING.to(FAILED)

    # Disputes
    buyer_disputes = FUNDED.to(DISPUTED) | IN_PROGRESS.to(DISPUTED)
    dispute_resolved_for_worker = DISPUTED.to(COMPLETED)
    dispute_resolved_for_buyer = DISPUTED.to(FAILED)

    def __init__(self, current_status: str = "CREATED") -> None:
        """Initialize the state machine at a given status.

        Args:
            current_status: The current EscrowStatus value (e.g., "FUNDED").
                           Must match one of the State value strings exactly.
        """
        # Validate that the status string is a known state value
        valid_values = {s.value for s in self.states}
        if current_status not in valid_values:
            valid = ", ".join(sorted(valid_values))
            raise ValueError(
                f"Unknown status '{current_status}'. Valid states: {valid}"
            )
        # start_value expects the string value, not the State object
        super().__init__(start_value=current_status)

    @property
    def status(self) -> str:
        """Return the current state value as a string (matches EscrowStatus enum)."""
        return str(self.current_state.value)

    def get_allowed_events(self) -> list[str]:
        """Return a list of event names that can fire from the current state."""
        return [event.name for event in self.allowed_events]


def validate_transition(current_status: str, event_name: str) -> str:
    """Validate a state transition and return the new status.

    This is a convenience function that creates a temporary state machine,
    fires the named event, and returns the resulting status string.

    Args:
        current_status: Current EscrowStatus value.
        event_name: The event to fire (e.g., "worker_accepts").

    Returns:
        The new status string after the transition.

    Raises:
        TransitionNotAllowed: If the transition is illegal.
        ValueError: If the status or event name is invalid.
    """
    sm = EscrowStateMachine(current_status=current_status)

    # Get the event method from the state machine
    event_method = getattr(sm, event_name, None)
    if event_method is None or not callable(event_method):
        raise ValueError(
            f"Unknown event '{event_name}'. "
            f"Allowed events from {current_status}: {sm.get_allowed_events()}"
        )

    event_method()
    return sm.status
