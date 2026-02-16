"""Verifier Strategy Protocol.

Defines the interface that all verification strategies must implement.
This is a Protocol (structural subtyping) so concrete verifiers don't need
to inherit from a base class — they just need to match the shape.

The domain layer has ZERO imports from E2B, LiteLLM, or any external service.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class VerificationRequest:
    """Input to a verifier.

    Attributes:
        contract_id: UUID of the escrow contract.
        payload: The work submitted by the worker (code, JSON, text).
        verification_config: The verification_logic JSON from the contract.
        requirements_schema: The requirements_schema JSON (for schema verifier).
    """

    contract_id: str
    payload: str
    verification_config: dict
    requirements_schema: dict | None = None


@dataclass(frozen=True)
class VerificationResult:
    """Output from a verifier.

    Attributes:
        is_valid: Whether the work meets the criteria.
        score: Optional numeric score (0.0 - 1.0) for semantic verification.
        details: Human-readable explanation of the result.
        logs: Raw logs from execution (stdout, stderr, LLM response).
        error: Error message if the verifier itself failed (not the work).
    """

    is_valid: bool
    score: float | None = None
    details: str = ""
    logs: dict = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict:
        """Serialize for storage in verification_result JSON column."""
        return {
            "is_valid": self.is_valid,
            "score": self.score,
            "details": self.details,
            "logs": self.logs,
            "error": self.error,
        }


@runtime_checkable
class VerifierStrategy(Protocol):
    """Protocol that all verifier implementations must satisfy.

    Concrete implementations:
        - verifiers/code_execution.py  (E2B sandbox)
        - verifiers/semantic.py        (LiteLLM LLM judge)
        - verifiers/schema_validator.py (JSON Schema / Pydantic)
    """

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        """Execute verification against the submitted work.

        Args:
            request: The verification request containing payload and config.

        Returns:
            A VerificationResult with is_valid, details, and logs.
        """
        ...
