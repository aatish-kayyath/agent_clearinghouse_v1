"""Verification Service — orchestrates the verify-then-settle pipeline.

Coordinates between:
    - EscrowService (state transitions)
    - VerifierFactory (dispatch to correct verifier)
    - VerificationResult (structured output)

This is the service that the LangGraph VERIFIER node calls.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from agentic_clearinghouse.domain.verifier_protocol import (
    VerificationRequest,
    VerificationResult,
)
from agentic_clearinghouse.infrastructure.database.repositories import (
    EscrowRepository,
    SubmissionRepository,
)
from agentic_clearinghouse.logging_config import get_logger
from agentic_clearinghouse.services.escrow_service import EscrowService
from agentic_clearinghouse.verifiers import VerifierFactory

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


class VerificationService:
    """Runs verification on the latest submission for a contract."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._escrow_service = EscrowService(session)
        self._escrow_repo = EscrowRepository(session)
        self._submission_repo = SubmissionRepository(session)

    async def verify_latest_submission(
        self, contract_id: uuid.UUID
    ) -> VerificationResult:
        """Run the full verification pipeline for a contract.

        1. Transition to VERIFYING
        2. Get the latest submission
        3. Dispatch to the correct verifier
        4. Record result (pass -> COMPLETED, fail -> IN_PROGRESS or FAILED)

        Returns:
            The VerificationResult from the verifier.
        """
        # Step 1: Transition to VERIFYING
        contract = await self._escrow_service.start_verification(contract_id)

        # Step 2: Get latest submission
        submissions = await self._submission_repo.get_by_contract(contract_id)
        if not submissions:
            result = VerificationResult(
                is_valid=False,
                details="No submissions found for this contract.",
                error="NO_SUBMISSIONS",
            )
            await self._escrow_service.record_verification_failed(
                contract_id=contract_id,
                submission_id=uuid.uuid4(),  # placeholder
                verification_result=result.to_dict(),
            )
            return result

        latest_submission = submissions[0]  # newest first

        # Step 3: Dispatch to verifier
        logger.info(
            "verification.dispatching",
            contract_id=str(contract_id),
            verifier_type=contract.verification_logic.get("type"),
            submission_id=str(latest_submission.id),
        )

        verifier = VerifierFactory.create(contract.verification_logic)

        request = VerificationRequest(
            contract_id=str(contract_id),
            payload=latest_submission.payload,
            verification_config=contract.verification_logic,
            requirements_schema=contract.requirements_schema,
        )

        result = await verifier.verify(request)

        # Step 4: Record the result
        if result.is_valid:
            await self._escrow_service.record_verification_passed(
                contract_id=contract_id,
                submission_id=latest_submission.id,
                verification_result=result.to_dict(),
            )
            logger.info(
                "verification.passed",
                contract_id=str(contract_id),
                score=result.score,
            )
        else:
            await self._escrow_service.record_verification_failed(
                contract_id=contract_id,
                submission_id=latest_submission.id,
                verification_result=result.to_dict(),
            )
            logger.info(
                "verification.failed",
                contract_id=str(contract_id),
                error=result.error,
                details=result.details[:100],
            )

        return result
