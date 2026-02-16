"""Domain exceptions for the Agentic Clearinghouse.

These exceptions are framework-agnostic and represent business rule violations.
They are caught and translated to HTTP responses by the API layer's middleware.
"""


class ClearinghouseError(Exception):
    """Base exception for all domain errors."""

    def __init__(self, message: str, code: str = "CLEARINGHOUSE_ERROR") -> None:
        self.message = message
        self.code = code
        super().__init__(self.message)


# --- State Machine Errors ---


class InvalidStateTransitionError(ClearinghouseError):
    """Raised when an attempted state transition is not allowed.

    Example: CREATED -> COMPLETED (must go through FUNDED, IN_PROGRESS, etc.)
    """

    def __init__(self, current_state: str, attempted_state: str) -> None:
        super().__init__(
            message=f"Invalid state transition: {current_state} -> {attempted_state}",
            code="INVALID_STATE_TRANSITION",
        )
        self.current_state = current_state
        self.attempted_state = attempted_state


# --- Contract Errors ---


class ContractNotFoundError(ClearinghouseError):
    """Raised when a contract ID does not exist."""

    def __init__(self, contract_id: str) -> None:
        super().__init__(
            message=f"Contract not found: {contract_id}",
            code="CONTRACT_NOT_FOUND",
        )
        self.contract_id = contract_id


class ContractAlreadyFundedError(ClearinghouseError):
    """Raised when trying to fund a contract that is already funded."""

    def __init__(self, contract_id: str) -> None:
        super().__init__(
            message=f"Contract already funded: {contract_id}",
            code="CONTRACT_ALREADY_FUNDED",
        )


class WorkerAlreadyAssignedError(ClearinghouseError):
    """Raised when a worker tries to accept a contract that already has one."""

    def __init__(self, contract_id: str) -> None:
        super().__init__(
            message=f"Worker already assigned to contract: {contract_id}",
            code="WORKER_ALREADY_ASSIGNED",
        )


# --- Verification Errors ---


class VerificationError(ClearinghouseError):
    """Base exception for verification failures."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message=message, code="VERIFICATION_ERROR")
        self.details = details or {}


class SandboxExecutionError(VerificationError):
    """Raised when code execution in E2B sandbox fails."""

    def __init__(self, message: str, stderr: str = "", exit_code: int | None = None) -> None:
        super().__init__(
            message=message,
            details={"stderr": stderr, "exit_code": exit_code},
        )
        self.code = "SANDBOX_EXECUTION_ERROR"


class SchemaValidationError(VerificationError):
    """Raised when submitted work fails JSON schema validation."""

    def __init__(self, message: str, validation_errors: list | None = None) -> None:
        super().__init__(
            message=message,
            details={"validation_errors": validation_errors or []},
        )
        self.code = "SCHEMA_VALIDATION_ERROR"


class SemanticJudgementError(VerificationError):
    """Raised when the LLM judge fails or returns an ambiguous result."""

    def __init__(self, message: str, llm_response: str = "") -> None:
        super().__init__(
            message=message,
            details={"llm_response": llm_response},
        )
        self.code = "SEMANTIC_JUDGEMENT_ERROR"


# --- Payment Errors ---


class PaymentError(ClearinghouseError):
    """Raised when a crypto payment operation fails."""

    def __init__(self, message: str, tx_hash: str | None = None) -> None:
        super().__init__(message=message, code="PAYMENT_ERROR")
        self.tx_hash = tx_hash


class InsufficientFundsError(PaymentError):
    """Raised when the escrow wallet has insufficient USDC."""

    def __init__(self, required: str, available: str) -> None:
        super().__init__(
            message=f"Insufficient funds: required {required} USDC, available {available} USDC",
        )
        self.code = "INSUFFICIENT_FUNDS"


# --- Idempotency Errors ---


class DuplicateOperationError(ClearinghouseError):
    """Raised when a duplicate idempotency key is detected."""

    def __init__(self, idempotency_key: str) -> None:
        super().__init__(
            message=f"Duplicate operation detected for key: {idempotency_key}",
            code="DUPLICATE_OPERATION",
        )
