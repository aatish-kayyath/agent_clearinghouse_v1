"""Repository classes for database access.

Repositories encapsulate all SQL queries and provide a clean interface
to the service layer. They accept an AsyncSession and never manage
their own transactions (that's the caller's responsibility).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from agentic_clearinghouse.infrastructure.database.orm_models import (
    EscrowContract,
    EscrowEvent,
    WorkSubmission,
)

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from agentic_clearinghouse.domain.enums import EscrowStatus, EventType


class EscrowRepository:
    """Data access for escrow contracts."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, contract: EscrowContract) -> EscrowContract:
        """Insert a new escrow contract."""
        self._session.add(contract)
        await self._session.flush()
        return contract

    async def get_by_id(self, contract_id: uuid.UUID) -> EscrowContract | None:
        """Fetch a contract by its UUID."""
        result = await self._session.execute(
            select(EscrowContract).where(EscrowContract.id == contract_id)
        )
        return result.scalar_one_or_none()

    async def get_by_status(self, status: EscrowStatus) -> list[EscrowContract]:
        """Fetch all contracts with a given status."""
        result = await self._session.execute(
            select(EscrowContract)
            .where(EscrowContract.status == status.value)
            .order_by(EscrowContract.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_buyer(self, buyer_wallet: str) -> list[EscrowContract]:
        """Fetch all contracts for a buyer wallet."""
        result = await self._session.execute(
            select(EscrowContract)
            .where(EscrowContract.buyer_wallet == buyer_wallet)
            .order_by(EscrowContract.created_at.desc())
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        contract: EscrowContract,
        new_status: EscrowStatus,
    ) -> EscrowContract:
        """Update the status of a contract (call AFTER state machine validation)."""
        contract.status = new_status.value
        contract.updated_at = datetime.now(UTC)
        await self._session.flush()
        return contract

    async def increment_retry(self, contract: EscrowContract) -> EscrowContract:
        """Increment the retry counter on a contract."""
        contract.retry_count += 1
        contract.updated_at = datetime.now(UTC)
        await self._session.flush()
        return contract


class SubmissionRepository:
    """Data access for work submissions."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, submission: WorkSubmission) -> WorkSubmission:
        """Insert a new work submission."""
        self._session.add(submission)
        await self._session.flush()
        return submission

    async def get_by_id(self, submission_id: uuid.UUID) -> WorkSubmission | None:
        """Fetch a submission by its UUID."""
        result = await self._session.execute(
            select(WorkSubmission).where(WorkSubmission.id == submission_id)
        )
        return result.scalar_one_or_none()

    async def get_by_contract(self, contract_id: uuid.UUID) -> list[WorkSubmission]:
        """Fetch all submissions for a contract, newest first."""
        result = await self._session.execute(
            select(WorkSubmission)
            .where(WorkSubmission.contract_id == contract_id)
            .order_by(WorkSubmission.submitted_at.desc())
        )
        return list(result.scalars().all())

    async def update_verification(
        self,
        submission: WorkSubmission,
        is_valid: bool,
        verification_result: dict,
    ) -> WorkSubmission:
        """Record the verification outcome on a submission."""
        submission.is_valid = is_valid
        submission.verification_result = verification_result
        await self._session.flush()
        return submission


class EventRepository:
    """Data access for the append-only audit event log."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        contract_id: uuid.UUID,
        event_type: EventType,
        old_status: EscrowStatus | None,
        new_status: EscrowStatus,
        actor: str = "SYSTEM",
        metadata: dict | None = None,
    ) -> EscrowEvent:
        """Append a new audit event. This is the ONLY write operation allowed."""
        evt = EscrowEvent(
            contract_id=contract_id,
            event_type=event_type.value,
            old_status=old_status.value if old_status else None,
            new_status=new_status.value,
            actor=actor,
            metadata_json=metadata,
        )
        self._session.add(evt)
        await self._session.flush()
        return evt

    async def get_by_contract(self, contract_id: uuid.UUID) -> list[EscrowEvent]:
        """Fetch all events for a contract in chronological order."""
        result = await self._session.execute(
            select(EscrowEvent)
            .where(EscrowEvent.contract_id == contract_id)
            .order_by(EscrowEvent.created_at.asc())
        )
        return list(result.scalars().all())
