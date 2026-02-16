"""Escrow Service — core business logic for contract lifecycle.

This is the application layer that coordinates between:
    - Domain state machine (transition guard)
    - Repositories (data access)
    - Event log (audit trail)

Both REST routes and MCP tools call into this service,
ensuring a single source of truth for all business rules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentic_clearinghouse.domain.enums import EscrowStatus, EventType
from agentic_clearinghouse.domain.exceptions import (
    ContractNotFoundError,
    InvalidStateTransitionError,
    WorkerAlreadyAssignedError,
)
from agentic_clearinghouse.domain.state_machine import EscrowStateMachine
from agentic_clearinghouse.infrastructure.database.orm_models import (
    EscrowContract,
    WorkSubmission,
)
from agentic_clearinghouse.infrastructure.database.repositories import (
    EscrowRepository,
    EventRepository,
    SubmissionRepository,
)
from agentic_clearinghouse.logging_config import get_logger

if TYPE_CHECKING:
    import uuid
    from decimal import Decimal

    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class EscrowService:
    """Manages the escrow contract lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._escrow_repo = EscrowRepository(session)
        self._submission_repo = SubmissionRepository(session)
        self._event_repo = EventRepository(session)

    # ------------------------------------------------------------------
    # Contract Creation
    # ------------------------------------------------------------------

    async def create_contract(
        self,
        buyer_wallet: str,
        amount_usdc: Decimal,
        description: str,
        verification_logic: dict,
        requirements_schema: dict | None = None,
        max_retries: int = 3,
    ) -> EscrowContract:
        """Create a new escrow contract in CREATED state."""
        contract = EscrowContract(
            buyer_wallet=buyer_wallet,
            amount_usdc=amount_usdc,
            description=description,
            requirements_schema=requirements_schema,
            verification_logic=verification_logic,
            max_retries=max_retries,
            status=EscrowStatus.CREATED.value,
        )
        contract = await self._escrow_repo.create(contract)

        await self._event_repo.record(
            contract_id=contract.id,
            event_type=EventType.CONTRACT_CREATED,
            old_status=None,
            new_status=EscrowStatus.CREATED,
            actor=buyer_wallet,
            metadata={"description": description},
        )

        logger.info("escrow.created", contract_id=str(contract.id), amount=str(amount_usdc))
        return contract

    # ------------------------------------------------------------------
    # Funding
    # ------------------------------------------------------------------

    async def fund_contract(
        self,
        contract_id: uuid.UUID,
        tx_hash: str,
        escrow_wallet_address: str,
    ) -> EscrowContract:
        """Record on-chain funding and transition to FUNDED."""
        contract = await self._get_contract_or_raise(contract_id)

        # Guard transition
        self._fire_transition(contract, "on_chain_confirmed")

        contract.funding_tx_hash = tx_hash
        contract.escrow_wallet_address = escrow_wallet_address
        await self._escrow_repo.update_status(contract, EscrowStatus.FUNDED)

        await self._event_repo.record(
            contract_id=contract.id,
            event_type=EventType.CONTRACT_FUNDED,
            old_status=EscrowStatus.CREATED,
            new_status=EscrowStatus.FUNDED,
            actor="SYSTEM",
            metadata={"tx_hash": tx_hash, "escrow_wallet": escrow_wallet_address},
        )

        logger.info("escrow.funded", contract_id=str(contract_id), tx_hash=tx_hash)
        return contract

    # ------------------------------------------------------------------
    # Worker Assignment
    # ------------------------------------------------------------------

    async def accept_contract(
        self,
        contract_id: uuid.UUID,
        worker_wallet: str,
    ) -> EscrowContract:
        """Worker accepts a contract and transitions to IN_PROGRESS."""
        contract = await self._get_contract_or_raise(contract_id)

        if contract.worker_wallet is not None:
            raise WorkerAlreadyAssignedError(str(contract_id))

        self._fire_transition(contract, "worker_accepts")

        contract.worker_wallet = worker_wallet
        await self._escrow_repo.update_status(contract, EscrowStatus.IN_PROGRESS)

        await self._event_repo.record(
            contract_id=contract.id,
            event_type=EventType.WORKER_ASSIGNED,
            old_status=EscrowStatus.FUNDED,
            new_status=EscrowStatus.IN_PROGRESS,
            actor=worker_wallet,
        )

        logger.info("escrow.worker_accepted", contract_id=str(contract_id), worker=worker_wallet)
        return contract

    # ------------------------------------------------------------------
    # Work Submission
    # ------------------------------------------------------------------

    async def submit_work(
        self,
        contract_id: uuid.UUID,
        payload: str,
        worker_wallet: str | None = None,
    ) -> WorkSubmission:
        """Submit work and transition to SUBMITTED."""
        contract = await self._get_contract_or_raise(contract_id)

        self._fire_transition(contract, "worker_submits")
        await self._escrow_repo.update_status(contract, EscrowStatus.SUBMITTED)

        submission = WorkSubmission(
            contract_id=contract.id,
            payload=payload,
            submitted_by=worker_wallet or contract.worker_wallet,
        )
        submission = await self._submission_repo.create(submission)

        await self._event_repo.record(
            contract_id=contract.id,
            event_type=EventType.WORK_SUBMITTED,
            old_status=EscrowStatus.IN_PROGRESS,
            new_status=EscrowStatus.SUBMITTED,
            actor=worker_wallet or contract.worker_wallet or "UNKNOWN",
            metadata={"submission_id": str(submission.id)},
        )

        logger.info(
            "escrow.work_submitted",
            contract_id=str(contract_id),
            submission_id=str(submission.id),
        )
        return submission

    # ------------------------------------------------------------------
    # Verification (called by the LangGraph orchestrator)
    # ------------------------------------------------------------------

    async def start_verification(self, contract_id: uuid.UUID) -> EscrowContract:
        """Transition from SUBMITTED to VERIFYING."""
        contract = await self._get_contract_or_raise(contract_id)
        self._fire_transition(contract, "auto_verify")
        await self._escrow_repo.update_status(contract, EscrowStatus.VERIFYING)

        await self._event_repo.record(
            contract_id=contract.id,
            event_type=EventType.VERIFICATION_STARTED,
            old_status=EscrowStatus.SUBMITTED,
            new_status=EscrowStatus.VERIFYING,
            actor="SYSTEM",
        )
        return contract

    async def record_verification_passed(
        self,
        contract_id: uuid.UUID,
        submission_id: uuid.UUID,
        verification_result: dict,
    ) -> EscrowContract:
        """Record successful verification and transition to COMPLETED."""
        contract = await self._get_contract_or_raise(contract_id)
        self._fire_transition(contract, "verification_passed")
        await self._escrow_repo.update_status(contract, EscrowStatus.COMPLETED)

        # Update the submission record
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission:
            await self._submission_repo.update_verification(
                submission, is_valid=True, verification_result=verification_result
            )

        await self._event_repo.record(
            contract_id=contract.id,
            event_type=EventType.VERIFICATION_PASSED,
            old_status=EscrowStatus.VERIFYING,
            new_status=EscrowStatus.COMPLETED,
            actor="SYSTEM",
            metadata=verification_result,
        )

        logger.info("escrow.verification_passed", contract_id=str(contract_id))
        return contract

    async def record_verification_failed(
        self,
        contract_id: uuid.UUID,
        submission_id: uuid.UUID,
        verification_result: dict,
    ) -> EscrowContract:
        """Record failed verification — retry or fail permanently."""
        contract = await self._get_contract_or_raise(contract_id)

        # Update the submission record
        submission = await self._submission_repo.get_by_id(submission_id)
        if submission:
            await self._submission_repo.update_verification(
                submission, is_valid=False, verification_result=verification_result
            )

        await self._escrow_repo.increment_retry(contract)

        if contract.retry_count >= contract.max_retries:
            # Max retries exceeded — FAIL
            self._fire_transition(contract, "max_retries_exceeded")
            await self._escrow_repo.update_status(contract, EscrowStatus.FAILED)

            await self._event_repo.record(
                contract_id=contract.id,
                event_type=EventType.MAX_RETRIES_EXCEEDED,
                old_status=EscrowStatus.VERIFYING,
                new_status=EscrowStatus.FAILED,
                actor="SYSTEM",
                metadata={"retry_count": contract.retry_count, **verification_result},
            )
            logger.info("escrow.max_retries_exceeded", contract_id=str(contract_id))
        else:
            # Retry — back to IN_PROGRESS
            self._fire_transition(contract, "verification_failed_retry")
            await self._escrow_repo.update_status(contract, EscrowStatus.IN_PROGRESS)

            await self._event_repo.record(
                contract_id=contract.id,
                event_type=EventType.VERIFICATION_FAILED,
                old_status=EscrowStatus.VERIFYING,
                new_status=EscrowStatus.IN_PROGRESS,
                actor="SYSTEM",
                metadata={"retry_count": contract.retry_count, **verification_result},
            )
            logger.info(
                "escrow.verification_failed_retry",
                contract_id=str(contract_id),
                retry=contract.retry_count,
            )

        return contract

    # ------------------------------------------------------------------
    # Disputes
    # ------------------------------------------------------------------

    async def raise_dispute(
        self,
        contract_id: uuid.UUID,
        reason: str,
        raised_by: str,
    ) -> EscrowContract:
        """Raise a dispute on a contract."""
        contract = await self._get_contract_or_raise(contract_id)
        old_status = EscrowStatus(contract.status)

        self._fire_transition(contract, "buyer_disputes")
        await self._escrow_repo.update_status(contract, EscrowStatus.DISPUTED)

        await self._event_repo.record(
            contract_id=contract.id,
            event_type=EventType.DISPUTE_RAISED,
            old_status=old_status,
            new_status=EscrowStatus.DISPUTED,
            actor=raised_by,
            metadata={"reason": reason},
        )

        logger.info("escrow.dispute_raised", contract_id=str(contract_id), by=raised_by)
        return contract

    # ------------------------------------------------------------------
    # Read helpers
    # ------------------------------------------------------------------

    async def get_contract(self, contract_id: uuid.UUID) -> EscrowContract:
        """Get a contract or raise."""
        return await self._get_contract_or_raise(contract_id)

    async def get_status(self, contract_id: uuid.UUID) -> dict:
        """Get contract status with allowed events."""
        contract = await self._get_contract_or_raise(contract_id)
        sm = EscrowStateMachine(current_status=contract.status)
        return {
            "contract_id": str(contract.id),
            "status": contract.status,
            "retry_count": contract.retry_count,
            "max_retries": contract.max_retries,
            "allowed_events": sm.get_allowed_events(),
        }

    async def get_events(self, contract_id: uuid.UUID) -> list:
        """Get audit trail."""
        return await self._event_repo.get_by_contract(contract_id)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_contract_or_raise(self, contract_id: uuid.UUID) -> EscrowContract:
        contract = await self._escrow_repo.get_by_id(contract_id)
        if contract is None:
            raise ContractNotFoundError(str(contract_id))
        return contract

    def _fire_transition(self, contract: EscrowContract, event_name: str) -> None:
        """Validate and fire a state machine transition.

        Raises InvalidStateTransitionError if the transition is illegal.
        """
        from statemachine.exceptions import TransitionNotAllowed

        sm = EscrowStateMachine(current_status=contract.status)
        event_method = getattr(sm, event_name, None)
        if event_method is None:
            raise InvalidStateTransitionError(contract.status, event_name)
        try:
            event_method()
        except TransitionNotAllowed as err:
            raise InvalidStateTransitionError(contract.status, event_name) from err
