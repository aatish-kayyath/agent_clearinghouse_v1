#!/usr/bin/env python3
"""Agentic Clearinghouse — End-to-End Simulation.

Simulates three scenarios with BuyerBot and WorkerBot agents:

    Scenario 1: Happy Path
        - Buyer creates code_execution escrow (Fibonacci)
        - Worker submits correct code -> COMPLETED + payment settled

    Scenario 2: Fail and Retry
        - Buyer creates code_execution escrow
        - Worker submits wrong code (1st attempt) -> verification fails
        - Worker submits correct code (2nd attempt) -> COMPLETED

    Scenario 3: Malicious Worker
        - Buyer creates semantic escrow (write a haiku)
        - Worker submits malicious code (os.system) -> verification fails
        - Worker keeps submitting garbage -> MAX_RETRIES_EXCEEDED -> FAILED

Usage:
    # Option A: With Docker (PostgreSQL):
    docker compose up -d
    uv run python simulation.py

    # Option B: Without Docker (SQLite in-memory):
    uv run python simulation.py --sqlite

    # Option C: Dry-run (no API calls at all — instant, no Docker, no E2B, no LLM):
    uv run python simulation.py --sqlite --dry-run

    # Run a specific scenario:
    uv run python simulation.py --sqlite --scenario 1
    uv run python simulation.py --sqlite --dry-run --scenario 1
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------------------
# Configure structured logging BEFORE importing app modules
# ---------------------------------------------------------------------------
from agentic_clearinghouse.logging_config import get_logger, setup_logging

setup_logging(log_level="INFO", json_logs=False)
logger = get_logger("simulation")

# Module-level state
_sqlite_engine = None
_sqlite_session_factory = None
_dry_run = False


def set_dry_run(enabled: bool) -> None:
    """Enable or disable dry-run mode (mock verifiers, no API calls)."""
    global _dry_run
    _dry_run = enabled


def _mock_logic(should_pass: bool = True) -> dict:
    """Return mock verification_logic for dry-run mode."""
    return {"type": "mock", "should_pass": should_pass}


def _resolve_verification_logic(real_logic: dict, should_pass: bool = True) -> dict:
    """Return mock logic in dry-run mode, otherwise the real logic."""
    if _dry_run:
        return _mock_logic(should_pass=should_pass)
    return real_logic


async def _swap_verification_logic(session: Any, contract_id: str, should_pass: bool) -> None:
    """In dry-run mode, update the contract's verification_logic to flip pass/fail.

    This allows scenarios like fail-then-retry to work without real APIs.
    No-op when not in dry-run mode.
    """
    if not _dry_run:
        return
    from agentic_clearinghouse.services.escrow_service import EscrowService

    svc = EscrowService(session)
    contract = await svc.get_contract(uuid.UUID(contract_id))
    contract.verification_logic = _mock_logic(should_pass=should_pass)
    await session.flush()


# ---------------------------------------------------------------------------
# Database lifecycle helpers
# ---------------------------------------------------------------------------
async def init_database(use_sqlite: bool = False):
    """Initialize database engine and create tables."""
    global _sqlite_engine, _sqlite_session_factory

    if use_sqlite:
        # Register JSONB -> JSON adapter so SQLite can handle PostgreSQL JSONB columns
        from sqlalchemy.dialects import sqlite as sqlite_dialect
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from agentic_clearinghouse.infrastructure.database.orm_models import Base
        sqlite_dialect.base.SQLiteTypeCompiler.visit_JSONB = (
            sqlite_dialect.base.SQLiteTypeCompiler.visit_JSON
        )

        _sqlite_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            echo=False,
        )
        _sqlite_session_factory = async_sessionmaker(
            bind=_sqlite_engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        async with _sqlite_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("database.sqlite_initialized")
    else:
        from agentic_clearinghouse.infrastructure.database.engine import init_db
        await init_db()


async def get_session():
    """Get a fresh database session."""
    if _sqlite_session_factory is not None:
        return _sqlite_session_factory()

    from agentic_clearinghouse.infrastructure.database.engine import _get_session_factory
    factory = _get_session_factory()
    return factory()


async def shutdown_database():
    """Close database connections."""
    global _sqlite_engine, _sqlite_session_factory

    if _sqlite_engine is not None:
        await _sqlite_engine.dispose()
        _sqlite_engine = None
        _sqlite_session_factory = None
    else:
        from agentic_clearinghouse.infrastructure.database.engine import close_db
        await close_db()


# ---------------------------------------------------------------------------
# Bot Agents
# ---------------------------------------------------------------------------
@dataclass
class BuyerBot:
    """Simulated buyer agent that creates and funds escrow contracts."""

    wallet: str = "0x" + "B" * 40  # Buyer address

    async def create_escrow(
        self,
        session: Any,
        amount: Decimal,
        description: str,
        verification_logic: dict,
        max_retries: int = 3,
    ) -> str:
        """Create a new escrow contract. Returns contract_id."""
        from agentic_clearinghouse.services.escrow_service import EscrowService

        svc = EscrowService(session)
        contract = await svc.create_contract(
            buyer_wallet=self.wallet,
            amount_usdc=amount,
            description=description,
            verification_logic=verification_logic,
            max_retries=max_retries,
        )
        await session.commit()
        logger.info(
            "🔵 BUYER: Contract created",
            contract_id=str(contract.id),
            amount=str(amount),
        )
        return str(contract.id)

    async def fund_escrow(self, session: Any, contract_id: str) -> None:
        """Fund a contract with simulated payment."""
        from agentic_clearinghouse.services.escrow_service import EscrowService
        from agentic_clearinghouse.services.payment_service import PaymentService

        svc = EscrowService(session)
        payment = PaymentService(simulate=True)

        cid = uuid.UUID(contract_id)
        contract = await svc.get_contract(cid)

        escrow_wallet = await payment.create_escrow_wallet()
        tx_hash = await payment.simulate_funding(
            escrow_wallet=escrow_wallet,
            amount_usdc=contract.amount_usdc,
            buyer_wallet=self.wallet,
        )

        await svc.fund_contract(
            contract_id=cid,
            tx_hash=tx_hash,
            escrow_wallet_address=escrow_wallet,
        )
        await session.commit()
        logger.info(
            "🔵 BUYER: Contract funded",
            contract_id=contract_id,
            tx_hash=tx_hash[:16] + "...",
        )

    async def check_status(self, session: Any, contract_id: str) -> dict:
        """Check the current contract status."""
        from agentic_clearinghouse.services.escrow_service import EscrowService

        svc = EscrowService(session)
        status = await svc.get_status(uuid.UUID(contract_id))
        logger.info(
            "🔵 BUYER: Status check",
            contract_id=contract_id,
            status=status["status"],
            retries=f"{status['retry_count']}/{status['max_retries']}",
        )
        return status

    async def raise_dispute(self, session: Any, contract_id: str, reason: str) -> None:
        """Raise a dispute on a contract."""
        from agentic_clearinghouse.services.escrow_service import EscrowService

        svc = EscrowService(session)
        await svc.raise_dispute(
            contract_id=uuid.UUID(contract_id),
            reason=reason,
            raised_by=self.wallet,
        )
        await session.commit()
        logger.info("🔵 BUYER: Dispute raised", contract_id=contract_id)


@dataclass
class WorkerBot:
    """Simulated worker agent that accepts contracts and submits work."""

    wallet: str = "0x" + "W" * 40  # Worker address

    async def accept_contract(self, session: Any, contract_id: str) -> None:
        """Accept an escrow contract."""
        from agentic_clearinghouse.services.escrow_service import EscrowService

        svc = EscrowService(session)
        await svc.accept_contract(
            contract_id=uuid.UUID(contract_id),
            worker_wallet=self.wallet,
        )
        await session.commit()
        logger.info("🟢 WORKER: Contract accepted", contract_id=contract_id)

    async def submit_work(
        self,
        session: Any,
        contract_id: str,
        payload: str,
    ) -> dict:
        """Submit work and trigger the full verification pipeline.

        Returns the workflow result dict.
        """
        from agentic_clearinghouse.orchestration.escrow_graph import run_escrow_workflow

        logger.info(
            "🟢 WORKER: Submitting work",
            contract_id=contract_id,
            payload_preview=payload[:80] + ("..." if len(payload) > 80 else ""),
        )

        result = await run_escrow_workflow(
            contract_id=contract_id,
            session=session,
            payload=payload,
            worker_wallet=self.wallet,
        )
        await session.commit()

        if result.get("verification_passed"):
            logger.info(
                "🟢 WORKER: Work VERIFIED ✅",
                contract_id=contract_id,
                settlement_tx=result.get("settlement_tx_hash", "")[:16] + "...",
            )
        else:
            logger.info(
                "🟢 WORKER: Work REJECTED ❌",
                contract_id=contract_id,
                final_status=result.get("final_status"),
                error=result.get("error", ""),
            )

        return result


# ---------------------------------------------------------------------------
# Print helpers
# ---------------------------------------------------------------------------
def banner(text: str) -> None:
    """Print a prominent banner."""
    width = 70
    print("\n" + "=" * width)
    print(f"  {text}")
    print("=" * width + "\n")


def section(text: str) -> None:
    """Print a section header."""
    print(f"\n--- {text} ---\n")


def print_result(result: dict) -> None:
    """Pretty-print a workflow result."""
    passed = result.get("verification_passed", False)
    status_icon = "✅" if passed else "❌"
    print(f"  {status_icon} Verification: {'PASSED' if passed else 'FAILED'}")
    print(f"  Status: {result.get('final_status', 'UNKNOWN')}")
    if result.get("settlement_tx_hash"):
        print(f"  Settlement TX: {result['settlement_tx_hash'][:20]}...")
    vr = result.get("verification_result", {})
    if vr.get("score") is not None:
        print(f"  Score: {vr['score']}")
    if vr.get("details"):
        details = vr["details"]
        if len(details) > 200:
            details = details[:200] + "..."
        print(f"  Details: {details}")
    if vr.get("error"):
        print(f"  Error: {vr['error']}")
    if result.get("error"):
        print(f"  Workflow Error: {result['error']}")


async def print_audit_trail(session: Any, contract_id: str) -> None:
    """Print the full audit trail for a contract."""
    from agentic_clearinghouse.services.escrow_service import EscrowService

    svc = EscrowService(session)
    events = await svc.get_events(uuid.UUID(contract_id))
    print("\n  📜 Audit Trail:")
    for i, evt in enumerate(events, 1):
        old = evt.old_status or "—"
        print(f"    {i}. [{evt.event_type}] {old} → {evt.new_status} (by {evt.actor})")
    print()


# ===========================================================================
# Scenario 1: Happy Path
# ===========================================================================
async def scenario_1_happy_path() -> None:
    """Buyer creates Fibonacci escrow, worker submits correct code."""
    banner("SCENARIO 1: Happy Path — Fibonacci Code Execution")

    buyer = BuyerBot()
    worker = WorkerBot()

    session = await get_session()
    async with session:
        # Step 1: Buyer creates contract
        section("Step 1: Buyer creates escrow")
        contract_id = await buyer.create_escrow(
            session=session,
            amount=Decimal("50.00"),
            description="Write a Python function that prints the 10th Fibonacci number (55).",
            verification_logic=_resolve_verification_logic(
                {"type": "code_execution", "timeout": 30, "expected_output": "55"},
                should_pass=True,
            ),
            max_retries=3,
        )

        # Step 2: Buyer funds
        section("Step 2: Buyer funds contract")
        await buyer.fund_escrow(session, contract_id)

        # Step 3: Worker accepts
        section("Step 3: Worker accepts contract")
        await worker.accept_contract(session, contract_id)

        # Step 4: Worker submits correct code
        section("Step 4: Worker submits correct Fibonacci code")
        correct_code = """
def fibonacci(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

print(fibonacci(10))
"""
        result = await worker.submit_work(session, contract_id, correct_code.strip())
        print_result(result)

        # Step 5: Check final status
        section("Step 5: Final status check")
        await buyer.check_status(session, contract_id)

        # Audit trail
        await print_audit_trail(session, contract_id)

    return


# ===========================================================================
# Scenario 2: Fail and Retry
# ===========================================================================
async def scenario_2_fail_and_retry() -> None:
    """Worker submits wrong code first, then correct code on retry."""
    banner("SCENARIO 2: Fail and Retry — Wrong Output Then Correct")

    buyer = BuyerBot()
    worker = WorkerBot()

    session = await get_session()
    async with session:
        # Step 1: Create + Fund + Accept
        section("Step 1: Setup (Create -> Fund -> Accept)")
        contract_id = await buyer.create_escrow(
            session=session,
            amount=Decimal("75.00"),
            description="Print the sum of 1 to 100 (should be 5050).",
            verification_logic=_resolve_verification_logic(
                {"type": "code_execution", "timeout": 30, "expected_output": "5050"},
                should_pass=False,  # First attempt will fail
            ),
            max_retries=3,
        )
        await buyer.fund_escrow(session, contract_id)
        await worker.accept_contract(session, contract_id)

        # Step 2: Worker submits WRONG code
        section("Step 2: Worker submits wrong code (prints 5000)")
        wrong_code = "print(5000)"  # Wrong answer!
        result1 = await worker.submit_work(session, contract_id, wrong_code)
        print_result(result1)

        # Check status — should be back to IN_PROGRESS (retry available)
        status = await buyer.check_status(session, contract_id)
        assert status["status"] == "IN_PROGRESS", f"Expected IN_PROGRESS, got {status['status']}"
        print("  ✅ Contract back to IN_PROGRESS for retry")

        # Step 3: Worker submits CORRECT code
        section("Step 3: Worker submits correct code")
        await _swap_verification_logic(session, contract_id, should_pass=True)
        correct_code = "print(sum(range(1, 101)))"
        result2 = await worker.submit_work(session, contract_id, correct_code)
        print_result(result2)

        # Final check
        section("Step 4: Final status")
        await buyer.check_status(session, contract_id)
        await print_audit_trail(session, contract_id)


# ===========================================================================
# Scenario 3: Malicious Worker
# ===========================================================================
async def scenario_3_malicious_worker() -> None:
    """Worker repeatedly submits bad code until max retries exceeded."""
    banner("SCENARIO 3: Malicious Worker — Max Retries Exceeded")

    buyer = BuyerBot()
    worker = WorkerBot(wallet="0x" + "M" * 40)  # Malicious worker

    session = await get_session()
    async with session:
        # Step 1: Create + Fund + Accept
        section("Step 1: Setup (Create -> Fund -> Accept)")
        contract_id = await buyer.create_escrow(
            session=session,
            amount=Decimal("100.00"),
            description="Write a safe Python script that prints 'Hello, World!'",
            verification_logic=_resolve_verification_logic(
                {"type": "code_execution", "timeout": 10, "expected_output": "Hello, World!"},
                should_pass=False,  # Malicious worker always fails
            ),
            max_retries=2,  # Only 2 retries allowed
        )
        await buyer.fund_escrow(session, contract_id)
        await worker.accept_contract(session, contract_id)

        # Attempt 1: Submit garbage
        section("Attempt 1: Malicious worker submits wrong output")
        result1 = await worker.submit_work(
            session, contract_id,
            "print('I am a malicious agent! HAHAHA')",
        )
        print_result(result1)

        status = await buyer.check_status(session, contract_id)
        if status["status"] == "FAILED":
            print("  ⚠️  Contract already FAILED (max retries was 2, but retry_count hit it)")
        else:
            # Attempt 2: Submit more garbage
            section("Attempt 2: Malicious worker submits garbage again")
            result2 = await worker.submit_work(
                session, contract_id,
                "import sys; sys.exit(1)",
            )
            print_result(result2)

            status = await buyer.check_status(session, contract_id)
            if status["status"] == "FAILED":
                print("  ⚠️  Contract FAILED — max retries exceeded. Buyer funds protected!")
            else:
                # Attempt 3: One more try
                section("Attempt 3: Last garbage attempt")
                result3 = await worker.submit_work(
                    session, contract_id,
                    "print('still wrong')",
                )
                print_result(result3)

        # Final status
        section("Final Status")
        final_status = await buyer.check_status(session, contract_id)
        print(f"\n  🛡️  Contract final status: {final_status['status']}")
        print(f"  🛡️  Retries used: {final_status['retry_count']}/{final_status['max_retries']}")

        await print_audit_trail(session, contract_id)


# ===========================================================================
# Main
# ===========================================================================
async def run_all(use_sqlite: bool = False, dry_run: bool = False) -> None:
    """Run all scenarios sequentially."""
    set_dry_run(dry_run)
    await init_database(use_sqlite=use_sqlite)

    try:
        print("\n" + "🚀" * 35)
        print("  THE AGENTIC CLEARINGHOUSE — SIMULATION")
        print("  Trust Code, Not Agents.")
        db_type = "SQLite (in-memory)" if use_sqlite else "PostgreSQL"
        mode = "DRY-RUN (mock verifiers)" if dry_run else "LIVE (real APIs)"
        print(f"  Database: {db_type}")
        print(f"  Mode: {mode}")
        print("🚀" * 35 + "\n")

        await scenario_1_happy_path()
        await scenario_2_fail_and_retry()
        await scenario_3_malicious_worker()

        print("\n" + "=" * 70)
        print("  ✅ ALL SCENARIOS COMPLETED SUCCESSFULLY")
        print("=" * 70 + "\n")

    finally:
        await shutdown_database()


async def run_scenario(num: int, use_sqlite: bool = False, dry_run: bool = False) -> None:
    """Run a specific scenario."""
    set_dry_run(dry_run)
    await init_database(use_sqlite=use_sqlite)

    scenarios = {
        1: scenario_1_happy_path,
        2: scenario_2_fail_and_retry,
        3: scenario_3_malicious_worker,
    }

    try:
        if num not in scenarios:
            print(f"Unknown scenario {num}. Available: 1, 2, 3")
            return
        await scenarios[num]()
    finally:
        await shutdown_database()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agentic Clearinghouse Simulation")
    parser.add_argument(
        "--scenario",
        type=int,
        default=0,
        help="Run a specific scenario (1, 2, or 3). Default: run all.",
    )
    parser.add_argument(
        "--sqlite",
        action="store_true",
        help="Use SQLite in-memory instead of PostgreSQL (no Docker needed).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use mock verifiers instead of real E2B/LLM APIs (instant, no network).",
    )
    args = parser.parse_args()

    if args.scenario == 0:
        asyncio.run(run_all(use_sqlite=args.sqlite, dry_run=args.dry_run))
    else:
        asyncio.run(run_scenario(args.scenario, use_sqlite=args.sqlite, dry_run=args.dry_run))
