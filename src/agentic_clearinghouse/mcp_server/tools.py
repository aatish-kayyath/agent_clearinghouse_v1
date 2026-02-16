"""MCP Tool definitions for the Agentic Clearinghouse.

These tools expose the clearinghouse functionality via the Model Context Protocol,
allowing AI agents to discover and call them programmatically.

Tools:
    - create_escrow: Create a new escrow contract
    - fund_escrow: Record on-chain funding for a contract
    - accept_contract: Worker accepts a contract
    - submit_work: Submit work + trigger verification pipeline
    - check_status: Check the current status of a contract
    - raise_dispute: Raise a dispute against a contract

The MCP server is mounted into FastAPI at /mcp via app.mount().
Each tool manages its own database session (no FastAPI Depends available).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from mcp.server.fastmcp import FastMCP

from agentic_clearinghouse.logging_config import get_logger

logger = get_logger(__name__)

# Initialize the MCP server
# This will be mounted into the FastAPI app in main.py
mcp = FastMCP(
    "Agentic Clearinghouse",
    json_response=True,
)


async def _get_session():
    """Create a database session for MCP tool context (not in FastAPI request)."""
    from agentic_clearinghouse.infrastructure.database.engine import _get_session_factory

    factory = _get_session_factory()
    return factory()


@mcp.tool()
async def create_escrow(
    buyer_wallet: str,
    amount_usdc: float,
    description: str,
    verification_type: str = "code_execution",
    verification_timeout: int = 30,
    expected_output: str = "",
    criteria: str = "",
    max_retries: int = 3,
) -> dict:
    """Create a new escrow contract for hiring a worker agent.

    Args:
        buyer_wallet: Your EVM wallet address (0x-prefixed, 42 chars).
        amount_usdc: Amount of USDC to escrow.
        description: What you want the worker to do.
        verification_type: One of 'code_execution', 'semantic', or 'schema'.
        verification_timeout: Timeout in seconds for code execution.
        expected_output: Expected stdout for code execution verification.
        criteria: Criteria string for semantic verification.
        max_retries: Max verification attempts before FAILED (1-10).

    Returns:
        Contract details including the contract_id you'll need for future calls.
    """
    from agentic_clearinghouse.services.escrow_service import EscrowService

    # Build verification_logic dict
    verification_logic: dict = {"type": verification_type}
    if verification_type == "code_execution":
        verification_logic["timeout"] = verification_timeout
        if expected_output:
            verification_logic["expected_output"] = expected_output
    elif verification_type == "semantic":
        verification_logic["criteria"] = criteria
    # schema type doesn't need extra config

    session = await _get_session()
    try:
        async with session:
            svc = EscrowService(session)
            contract = await svc.create_contract(
                buyer_wallet=buyer_wallet,
                amount_usdc=Decimal(str(amount_usdc)),
                description=description,
                verification_logic=verification_logic,
                max_retries=max_retries,
            )
            await session.commit()

            return {
                "contract_id": str(contract.id),
                "status": contract.status,
                "buyer_wallet": contract.buyer_wallet,
                "amount_usdc": str(contract.amount_usdc),
                "description": contract.description,
                "verification_logic": contract.verification_logic,
                "max_retries": contract.max_retries,
                "message": "Contract created. Next step: fund the contract.",
            }
    except Exception as exc:
        logger.exception("mcp.create_escrow.error")
        return {"error": str(exc)}


@mcp.tool()
async def fund_escrow(
    contract_id: str,
    tx_hash: str = "",
    escrow_wallet_address: str = "",
) -> dict:
    """Record on-chain funding for an escrow contract.

    Args:
        contract_id: UUID of the escrow contract.
        tx_hash: Transaction hash of the funding. Leave empty to auto-simulate.
        escrow_wallet_address: Wallet holding funds. Leave empty to auto-generate.

    Returns:
        Updated contract details with FUNDED status.
    """
    from agentic_clearinghouse.services.escrow_service import EscrowService
    from agentic_clearinghouse.services.payment_service import PaymentService

    session = await _get_session()
    try:
        async with session:
            svc = EscrowService(session)
            payment = PaymentService(simulate=True)

            cid = uuid.UUID(contract_id)

            # Auto-generate if not provided
            if not escrow_wallet_address:
                escrow_wallet_address = await payment.create_escrow_wallet()
            if not tx_hash:
                contract = await svc.get_contract(cid)
                tx_hash = await payment.simulate_funding(
                    escrow_wallet=escrow_wallet_address,
                    amount_usdc=contract.amount_usdc,
                    buyer_wallet=contract.buyer_wallet,
                )

            contract = await svc.fund_contract(
                contract_id=cid,
                tx_hash=tx_hash,
                escrow_wallet_address=escrow_wallet_address,
            )
            await session.commit()

            return {
                "contract_id": str(contract.id),
                "status": contract.status,
                "funding_tx_hash": contract.funding_tx_hash,
                "escrow_wallet_address": contract.escrow_wallet_address,
                "message": "Contract funded. Next step: worker accepts the contract.",
            }
    except Exception as exc:
        logger.exception("mcp.fund_escrow.error")
        return {"error": str(exc)}


@mcp.tool()
async def accept_contract(
    contract_id: str,
    worker_wallet: str,
) -> dict:
    """Accept an escrow contract as a worker agent.

    Args:
        contract_id: UUID of the escrow contract.
        worker_wallet: Your EVM wallet address (0x-prefixed, 42 chars).

    Returns:
        Updated contract details with IN_PROGRESS status.
    """
    from agentic_clearinghouse.services.escrow_service import EscrowService

    session = await _get_session()
    try:
        async with session:
            svc = EscrowService(session)
            contract = await svc.accept_contract(
                contract_id=uuid.UUID(contract_id),
                worker_wallet=worker_wallet,
            )
            await session.commit()

            return {
                "contract_id": str(contract.id),
                "status": contract.status,
                "worker_wallet": contract.worker_wallet,
                "description": contract.description,
                "verification_logic": contract.verification_logic,
                "message": "Contract accepted. Submit your work when ready.",
            }
    except Exception as exc:
        logger.exception("mcp.accept_contract.error")
        return {"error": str(exc)}


@mcp.tool()
async def submit_work(
    contract_id: str,
    content: str,
    worker_wallet: str = "",
) -> dict:
    """Submit work against an escrow contract and trigger verification.

    This triggers the full workflow: submit -> verify -> settle/retry.

    Args:
        contract_id: UUID of the escrow contract to submit work for.
        content: The actual work (code, JSON, or text).
        worker_wallet: Your EVM wallet address (optional).

    Returns:
        Workflow result including verification outcome and settlement details.
    """
    from agentic_clearinghouse.orchestration.escrow_graph import run_escrow_workflow

    session = await _get_session()
    try:
        async with session:
            result = await run_escrow_workflow(
                contract_id=contract_id,
                session=session,
                payload=content,
                worker_wallet=worker_wallet or None,
            )
            await session.commit()

            return {
                "contract_id": result.get("contract_id"),
                "submission_id": result.get("submission_id"),
                "verification_passed": result.get("verification_passed"),
                "verification_result": result.get("verification_result"),
                "settlement_tx_hash": result.get("settlement_tx_hash"),
                "final_status": result.get("final_status"),
                "error": result.get("error"),
                "message": (
                    "Work verified and payment settled!"
                    if result.get("verification_passed")
                    else f"Verification failed. Status: {result.get('final_status')}"
                ),
            }
    except Exception as exc:
        logger.exception("mcp.submit_work.error")
        return {"error": str(exc)}


@mcp.tool()
async def check_status(contract_id: str) -> dict:
    """Check the current status of an escrow contract.

    Args:
        contract_id: UUID of the escrow contract.

    Returns:
        Current status, retry count, and allowed next actions.
    """
    from agentic_clearinghouse.services.escrow_service import EscrowService

    session = await _get_session()
    try:
        async with session:
            svc = EscrowService(session)
            status = await svc.get_status(uuid.UUID(contract_id))
            return status
    except Exception as exc:
        logger.exception("mcp.check_status.error")
        return {"error": str(exc)}


@mcp.tool()
async def raise_dispute(
    contract_id: str,
    reason: str,
    raised_by: str,
) -> dict:
    """Raise a dispute against an escrow contract.

    Args:
        contract_id: UUID of the escrow contract.
        reason: Detailed explanation of why you're disputing.
        raised_by: Your EVM wallet address.

    Returns:
        Updated contract status and dispute details.
    """
    from agentic_clearinghouse.services.escrow_service import EscrowService

    session = await _get_session()
    try:
        async with session:
            svc = EscrowService(session)
            contract = await svc.raise_dispute(
                contract_id=uuid.UUID(contract_id),
                reason=reason,
                raised_by=raised_by,
            )
            await session.commit()

            return {
                "contract_id": str(contract.id),
                "status": contract.status,
                "message": f"Dispute raised successfully. Contract is now {contract.status}.",
            }
    except Exception as exc:
        logger.exception("mcp.raise_dispute.error")
        return {"error": str(exc)}
