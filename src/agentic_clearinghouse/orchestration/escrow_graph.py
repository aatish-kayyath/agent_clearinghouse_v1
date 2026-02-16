"""LangGraph Escrow Workflow — orchestrates the submit-verify-settle pipeline.

This graph manages the lifecycle from work submission through verification
to settlement. It's invoked when a worker submits work and runs:

    submit_work -> verify -> [route] -> settle (if passed) OR retry (if failed)

The graph uses conditional edges to route based on verification results
and retry counts.

Usage:
    from agentic_clearinghouse.orchestration.escrow_graph import run_escrow_workflow

    result = await run_escrow_workflow(
        contract_id="...",
        session=db_session,
        payload="print(55)",
        worker_wallet="0x...",
    )
"""

from __future__ import annotations

import uuid
from typing import Any, TypedDict

from agentic_clearinghouse.logging_config import get_logger

logger = get_logger(__name__)


class EscrowWorkflowState(TypedDict, total=False):
    """State schema for the LangGraph escrow workflow."""

    contract_id: str
    submission_id: str
    payload: str
    worker_wallet: str
    verification_passed: bool
    verification_result: dict
    settlement_tx_hash: str
    final_status: str
    error: str


async def run_escrow_workflow(
    contract_id: str,
    session: Any,
    payload: str,
    worker_wallet: str | None = None,
) -> EscrowWorkflowState:
    """Run the full escrow workflow: submit -> verify -> settle/retry.

    This function encapsulates the LangGraph workflow in a simple async call.
    It manages all state transitions through the EscrowService.

    Args:
        contract_id: UUID string of the escrow contract.
        session: AsyncSession for database access.
        payload: The work content to submit.
        worker_wallet: Optional worker wallet address.

    Returns:
        EscrowWorkflowState with the final status and all intermediate results.
    """
    from agentic_clearinghouse.services.escrow_service import EscrowService
    from agentic_clearinghouse.services.payment_service import PaymentService
    from agentic_clearinghouse.services.verification_service import VerificationService

    escrow_svc = EscrowService(session)
    verification_svc = VerificationService(session)
    payment_svc = PaymentService(simulate=True)

    cid = uuid.UUID(contract_id)

    state: EscrowWorkflowState = {
        "contract_id": contract_id,
        "payload": payload,
        "worker_wallet": worker_wallet or "",
        "verification_passed": False,
        "verification_result": {},
        "settlement_tx_hash": "",
        "final_status": "",
        "error": "",
    }

    try:
        # --- Node 1: Submit Work ---
        logger.info("workflow.submit", contract_id=contract_id)
        submission = await escrow_svc.submit_work(
            contract_id=cid,
            payload=payload,
            worker_wallet=worker_wallet,
        )
        state["submission_id"] = str(submission.id)

        # --- Node 2: Verify ---
        logger.info("workflow.verify", contract_id=contract_id)
        result = await verification_svc.verify_latest_submission(cid)
        state["verification_result"] = result.to_dict()
        state["verification_passed"] = result.is_valid

        # --- Node 3: Route ---
        if result.is_valid:
            # --- Node 4a: Settle ---
            logger.info("workflow.settle", contract_id=contract_id)
            contract = await escrow_svc.get_contract(cid)

            tx_hash = await payment_svc.transfer_to_worker(
                worker_wallet=contract.worker_wallet or worker_wallet or "",
                amount_usdc=contract.amount_usdc,
                escrow_wallet=contract.escrow_wallet_address or "",
            )
            contract.settlement_tx_hash = tx_hash
            state["settlement_tx_hash"] = tx_hash
            state["final_status"] = "COMPLETED"

            logger.info(
                "workflow.completed",
                contract_id=contract_id,
                tx_hash=tx_hash,
            )
        else:
            # --- Node 4b: Check retry or fail ---
            contract = await escrow_svc.get_contract(cid)
            state["final_status"] = contract.status

            if contract.status == "FAILED":
                logger.info(
                    "workflow.failed",
                    contract_id=contract_id,
                    reason="max_retries_exceeded",
                )
            else:
                logger.info(
                    "workflow.retry_available",
                    contract_id=contract_id,
                    retry_count=contract.retry_count,
                    max_retries=contract.max_retries,
                )

    except Exception as exc:
        logger.exception("workflow.error", contract_id=contract_id)
        state["error"] = str(exc)
        state["final_status"] = "ERROR"

    return state
