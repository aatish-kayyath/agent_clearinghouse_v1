"""SQLAlchemy 2.0 ORM models for the Agentic Clearinghouse.

Three tables:
    1. escrow_contracts  — The escrow agreements between buyer and worker agents.
    2. work_submissions  — Work delivered by workers against a contract.
    3. escrow_events     — Append-only audit log of every state transition.

Design decisions:
    - UUIDs as primary keys (agent-friendly, no sequential leakage).
    - Decimal for USDC amounts (no floating point rounding errors).
    - JSON columns for flexible verification config and results.
    - CHECK constraint on status to prevent invalid enum values at DB level.
    - Indexes on hot-path query columns (status, buyer_wallet, contract_id).
    - escrow_events is append-only: no UPDATE or DELETE at the application level.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal  # noqa: TC003 - needed at runtime by SQLAlchemy Mapped[]

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    event,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


# ---------------------------------------------------------------------------
# Helper: auto-set updated_at on flush
# ---------------------------------------------------------------------------
def _set_updated_at(mapper, connection, target):  # noqa: ANN001
    """SQLAlchemy event listener that updates `updated_at` before flush."""
    if hasattr(target, "updated_at"):
        target.updated_at = datetime.now(UTC)


# ---------------------------------------------------------------------------
# 1. escrow_contracts
# ---------------------------------------------------------------------------
class EscrowContract(Base):
    """An escrow agreement between a buyer agent and a worker agent."""

    __tablename__ = "escrow_contracts"

    # --- Primary Key ---
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # --- Participants ---
    buyer_wallet: Mapped[str] = mapped_column(
        String(42),
        nullable=False,
        comment="EVM wallet address of the buyer agent",
    )
    worker_wallet: Mapped[str | None] = mapped_column(
        String(42),
        nullable=True,
        default=None,
        comment="EVM wallet address of the worker agent (set on acceptance)",
    )

    # --- Financials ---
    amount_usdc: Mapped[Decimal] = mapped_column(
        Numeric(18, 6),
        nullable=False,
        comment="Escrow amount in USDC (6 decimal precision)",
    )
    escrow_wallet_address: Mapped[str | None] = mapped_column(
        String(42),
        nullable=True,
        default=None,
        comment="On-chain wallet holding the escrowed funds",
    )
    funding_tx_hash: Mapped[str | None] = mapped_column(
        String(66),
        nullable=True,
        default=None,
        comment="Transaction hash of the funding operation",
    )
    settlement_tx_hash: Mapped[str | None] = mapped_column(
        String(66),
        nullable=True,
        default=None,
        comment="Transaction hash of the settlement (payout) operation",
    )

    # --- Status (Enum-guarded) ---
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="CREATED",
        comment="Current lifecycle state (guarded by EscrowStateMachine)",
    )

    # --- Task Definition ---
    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Human-readable description of the task",
    )
    requirements_schema: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="JSON Schema that the output must validate against",
    )
    verification_logic: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        comment='Verification config, e.g. {"type": "code_execution", "timeout": 30}',
    )

    # --- Retry Logic ---
    max_retries: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        comment="Maximum verification retry attempts before FAILED",
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="Current number of failed verification attempts",
    )

    # --- Timestamps ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    # --- Relationships ---
    work_submissions: Mapped[list[WorkSubmission]] = relationship(
        "WorkSubmission",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="WorkSubmission.submitted_at.desc()",
        lazy="selectin",
    )
    events: Mapped[list[EscrowEvent]] = relationship(
        "EscrowEvent",
        back_populates="contract",
        cascade="all, delete-orphan",
        order_by="EscrowEvent.created_at.asc()",
        lazy="selectin",
    )

    # --- Table Constraints & Indexes ---
    __table_args__ = (
        CheckConstraint(
            "status IN ('CREATED', 'FUNDED', 'IN_PROGRESS', 'SUBMITTED', "
            "'VERIFYING', 'COMPLETED', 'FAILED', 'DISPUTED')",
            name="ck_escrow_valid_status",
        ),
        CheckConstraint(
            "amount_usdc > 0",
            name="ck_escrow_positive_amount",
        ),
        CheckConstraint(
            "retry_count >= 0 AND retry_count <= max_retries",
            name="ck_escrow_retry_bounds",
        ),
        Index("idx_escrow_status", "status"),
        Index("idx_escrow_buyer", "buyer_wallet"),
        Index("idx_escrow_worker", "worker_wallet"),
        Index("idx_escrow_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<EscrowContract id={self.id} status={self.status} "
            f"amount={self.amount_usdc} USDC>"
        )


# ---------------------------------------------------------------------------
# 2. work_submissions
# ---------------------------------------------------------------------------
class WorkSubmission(Base):
    """A piece of work submitted by a worker agent against a contract."""

    __tablename__ = "work_submissions"

    # --- Primary Key ---
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # --- Foreign Key ---
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("escrow_contracts.id", ondelete="CASCADE"),
        nullable=False,
        comment="The escrow contract this submission is for",
    )

    # --- Submission Content ---
    payload: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="The actual work delivered (code, JSON, text)",
    )
    submitted_by: Mapped[str | None] = mapped_column(
        String(42),
        nullable=True,
        comment="Worker wallet address (denormalized for quick lookup)",
    )

    # --- Verification Outcome ---
    verification_result: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
        default=None,
        comment="Structured output from the verifier (logs, score, details)",
    )
    is_valid: Mapped[bool | None] = mapped_column(
        Boolean,
        nullable=True,
        default=None,
        comment="Whether the submission passed verification (null = pending)",
    )

    # --- Timestamps ---
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # --- Relationships ---
    contract: Mapped[EscrowContract] = relationship(
        "EscrowContract",
        back_populates="work_submissions",
    )

    # --- Indexes ---
    __table_args__ = (
        Index("idx_submission_contract", "contract_id"),
        Index("idx_submission_submitted_at", "submitted_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkSubmission id={self.id} contract={self.contract_id} "
            f"valid={self.is_valid}>"
        )


# ---------------------------------------------------------------------------
# 3. escrow_events (Append-Only Audit Log)
# ---------------------------------------------------------------------------
class EscrowEvent(Base):
    """Immutable audit record of every state transition in a contract's lifecycle.

    This table is APPEND-ONLY. No UPDATE or DELETE operations are permitted
    at the application level. Every row represents a single atomic event.
    """

    __tablename__ = "escrow_events"

    # --- Primary Key ---
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    # --- Foreign Key ---
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("escrow_contracts.id", ondelete="CASCADE"),
        nullable=False,
        comment="The escrow contract this event belongs to",
    )

    # --- Event Details ---
    event_type: Mapped[str] = mapped_column(
        String(40),
        nullable=False,
        comment="EventType enum value (e.g., CONTRACT_CREATED, VERIFICATION_PASSED)",
    )
    old_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="Contract status before this event (null for creation)",
    )
    new_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        comment="Contract status after this event",
    )
    actor: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="SYSTEM",
        comment="Who triggered this event (wallet address or SYSTEM)",
    )
    metadata_json: Mapped[dict | None] = mapped_column(
        "metadata",
        JSONB,
        nullable=True,
        default=None,
        comment="Arbitrary context: tx hash, error logs, verifier output",
    )

    # --- Timestamp ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    # --- Relationships ---
    contract: Mapped[EscrowContract] = relationship(
        "EscrowContract",
        back_populates="events",
    )

    # --- Indexes ---
    __table_args__ = (
        Index("idx_event_contract", "contract_id"),
        Index("idx_event_type", "event_type"),
        Index("idx_event_created_at", "created_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<EscrowEvent id={self.id} type={self.event_type} "
            f"{self.old_status}->{self.new_status}>"
        )


# ---------------------------------------------------------------------------
# Register the auto-update listener for updated_at
# ---------------------------------------------------------------------------
event.listen(EscrowContract, "before_update", _set_updated_at)
