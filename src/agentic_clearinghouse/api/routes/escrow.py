"""Escrow contract REST API routes.

These endpoints provide the HTTP interface for creating contracts,
funding, submitting work, and checking status. The MCP tools in
mcp_server/tools.py call the same service layer, ensuring consistency.

Routes:
    POST   /api/v1/escrow              — Create a new escrow contract
    GET    /api/v1/escrow/{id}         — Get contract details
    GET    /api/v1/escrow/{id}/status  — Get lightweight status check
    GET    /api/v1/escrow/{id}/events  — Get audit trail
    POST   /api/v1/escrow/{id}/fund    — Record on-chain funding
    POST   /api/v1/escrow/{id}/accept  — Worker accepts contract
    POST   /api/v1/escrow/{id}/submit  — Submit work + trigger verification
    POST   /api/v1/escrow/{id}/dispute — Raise dispute
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends

from agentic_clearinghouse.api.deps import get_db_session
from agentic_clearinghouse.logging_config import get_logger
from agentic_clearinghouse.schemas.escrow import (
    AcceptContractRequest,
    ContractStatusResponse,
    CreateEscrowRequest,
    EscrowEventResponse,
    EscrowResponse,
    FundEscrowRequest,
    RaiseDisputeRequest,
    SubmitWorkRequest,
)
from agentic_clearinghouse.services.escrow_service import EscrowService

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/escrow", tags=["Escrow"])
logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=EscrowResponse,
    status_code=201,
    summary="Create a new escrow contract",
)
async def create_escrow(
    request: CreateEscrowRequest,
    session: AsyncSession = Depends(get_db_session),
) -> EscrowResponse:
    """Create a new escrow contract in CREATED state."""
    svc = EscrowService(session)
    contract = await svc.create_contract(
        buyer_wallet=request.buyer_wallet,
        amount_usdc=request.amount_usdc,
        description=request.description,
        verification_logic=request.verification_logic,
        requirements_schema=request.requirements_schema,
        max_retries=request.max_retries,
    )
    return EscrowResponse.model_validate(contract)


# ---------------------------------------------------------------------------
# Fund
# ---------------------------------------------------------------------------


@router.post(
    "/{contract_id}/fund",
    response_model=EscrowResponse,
    summary="Record on-chain funding",
)
async def fund_escrow(
    contract_id: uuid.UUID,
    request: FundEscrowRequest,
    session: AsyncSession = Depends(get_db_session),
) -> EscrowResponse:
    """Record that a contract has been funded on-chain. Transitions CREATED -> FUNDED."""
    svc = EscrowService(session)
    contract = await svc.fund_contract(
        contract_id=contract_id,
        tx_hash=request.tx_hash,
        escrow_wallet_address=request.escrow_wallet_address,
    )
    return EscrowResponse.model_validate(contract)


# ---------------------------------------------------------------------------
# Accept
# ---------------------------------------------------------------------------


@router.post(
    "/{contract_id}/accept",
    response_model=EscrowResponse,
    summary="Worker accepts contract",
)
async def accept_escrow(
    contract_id: uuid.UUID,
    request: AcceptContractRequest,
    session: AsyncSession = Depends(get_db_session),
) -> EscrowResponse:
    """Worker agent accepts the contract. Transitions FUNDED -> IN_PROGRESS."""
    svc = EscrowService(session)
    contract = await svc.accept_contract(
        contract_id=contract_id,
        worker_wallet=request.worker_wallet,
    )
    return EscrowResponse.model_validate(contract)


# ---------------------------------------------------------------------------
# Submit Work + Verify + Settle
# ---------------------------------------------------------------------------


@router.post(
    "/{contract_id}/submit",
    summary="Submit work and trigger verification",
)
async def submit_work(
    contract_id: uuid.UUID,
    request: SubmitWorkRequest,
    session: AsyncSession = Depends(get_db_session),
) -> dict:
    """Submit work and run the full verification pipeline.

    Triggers: IN_PROGRESS -> SUBMITTED -> VERIFYING -> COMPLETED/FAILED.
    """
    from agentic_clearinghouse.orchestration.escrow_graph import run_escrow_workflow

    result = await run_escrow_workflow(
        contract_id=str(contract_id),
        session=session,
        payload=request.content,
        worker_wallet=request.worker_wallet,
    )
    return result


# ---------------------------------------------------------------------------
# Dispute
# ---------------------------------------------------------------------------


@router.post(
    "/{contract_id}/dispute",
    response_model=EscrowResponse,
    summary="Raise a dispute",
)
async def raise_dispute(
    contract_id: uuid.UUID,
    request: RaiseDisputeRequest,
    session: AsyncSession = Depends(get_db_session),
) -> EscrowResponse:
    """Raise a dispute on a contract. Valid from FUNDED or IN_PROGRESS."""
    svc = EscrowService(session)
    contract = await svc.raise_dispute(
        contract_id=contract_id,
        reason=request.reason,
        raised_by=request.raised_by,
    )
    return EscrowResponse.model_validate(contract)


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/{contract_id}",
    response_model=EscrowResponse,
    summary="Get contract details",
)
async def get_escrow(
    contract_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> EscrowResponse:
    """Fetch a contract by its UUID."""
    svc = EscrowService(session)
    contract = await svc.get_contract(contract_id)
    return EscrowResponse.model_validate(contract)


@router.get(
    "/{contract_id}/status",
    response_model=ContractStatusResponse,
    summary="Get lightweight status check",
)
async def get_status(
    contract_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> ContractStatusResponse:
    """Return the current status and allowed next actions."""
    svc = EscrowService(session)
    status_data = await svc.get_status(contract_id)
    return ContractStatusResponse(**status_data)


@router.get(
    "/{contract_id}/events",
    response_model=list[EscrowEventResponse],
    summary="Get audit trail",
)
async def get_events(
    contract_id: uuid.UUID,
    session: AsyncSession = Depends(get_db_session),
) -> list[EscrowEventResponse]:
    """Return the full audit trail for a contract."""
    svc = EscrowService(session)
    events = await svc.get_events(contract_id)
    return [EscrowEventResponse.model_validate(e) for e in events]
