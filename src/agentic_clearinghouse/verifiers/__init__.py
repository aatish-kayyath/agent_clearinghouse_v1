"""Verification strategy implementations and factory.

Four strategies:
    - SchemaVerifier:         Local JSON Schema validation
    - SemanticVerifier:       LLM judge via LiteLLM (Gemini/GPT-4o/Llama)
    - CodeExecutionVerifier:  Sandboxed execution via E2B
    - MockVerifier:           Instant configurable pass/fail for dry-run testing

The VerifierFactory creates the correct verifier based on the
verification_logic["type"] field in the contract.
"""

from agentic_clearinghouse.domain.enums import VerifierType
from agentic_clearinghouse.domain.verifier_protocol import (
    VerificationRequest,
    VerificationResult,
    VerifierStrategy,
)
from agentic_clearinghouse.verifiers.code_execution import CodeExecutionVerifier
from agentic_clearinghouse.verifiers.schema_validator import SchemaVerifier
from agentic_clearinghouse.verifiers.semantic import SemanticVerifier


class MockVerifier:
    """Instant mock verifier for dry-run simulations.

    Returns a configurable pass/fail result with zero network calls.
    Controlled via verification_config keys:
        - should_pass (bool): Whether verification passes. Default True.
        - score (float): Score to return. Default 1.0 if pass, 0.0 if fail.
        - details (str): Custom details message. Optional.
    """

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        should_pass = request.verification_config.get("should_pass", True)
        score = request.verification_config.get(
            "score", 1.0 if should_pass else 0.0
        )
        details = request.verification_config.get(
            "details",
            "Mock verification passed (dry-run mode)"
            if should_pass
            else "Mock verification failed (dry-run mode)",
        )
        return VerificationResult(
            is_valid=should_pass,
            score=score,
            details=details,
            logs={"mode": "dry-run", "verifier": "mock"},
        )


class VerifierFactory:
    """Factory that creates the correct verifier based on verification_logic type.

    Usage:
        verifier = VerifierFactory.create({"type": "code_execution", "timeout": 30})
        result = await verifier.verify(request)

        # Dry-run mode:
        verifier = VerifierFactory.create({"type": "mock", "should_pass": True})
        result = await verifier.verify(request)
    """

    _registry: dict[str, type] = {
        VerifierType.CODE_EXECUTION.value: CodeExecutionVerifier,
        VerifierType.SEMANTIC.value: SemanticVerifier,
        VerifierType.SCHEMA.value: SchemaVerifier,
        "mock": MockVerifier,
    }

    @classmethod
    def create(cls, verification_logic: dict) -> VerifierStrategy:
        """Create a verifier instance from the verification_logic config.

        Args:
            verification_logic: Dict with at least a "type" key.
                Example: {"type": "code_execution", "timeout": 30}

        Returns:
            A verifier instance that satisfies the VerifierStrategy protocol.

        Raises:
            ValueError: If the type is unknown or missing.
        """
        v_type = verification_logic.get("type")
        if not v_type:
            raise ValueError(
                "verification_logic must contain a 'type' key. "
                f"Valid types: {list(cls._registry.keys())}"
            )

        verifier_class = cls._registry.get(v_type)
        if verifier_class is None:
            raise ValueError(
                f"Unknown verifier type: '{v_type}'. "
                f"Valid types: {list(cls._registry.keys())}"
            )

        return verifier_class()

    @classmethod
    def get_supported_types(cls) -> list[str]:
        """Return the list of supported verifier type strings."""
        return list(cls._registry.keys())


__all__ = [
    "CodeExecutionVerifier",
    "MockVerifier",
    "SchemaVerifier",
    "SemanticVerifier",
    "VerifierFactory",
    "VerificationRequest",
    "VerificationResult",
    "VerifierStrategy",
]
