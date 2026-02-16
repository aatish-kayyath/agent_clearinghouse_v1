"""Pydantic schemas for the Escrow API.

These schemas define the request/response shapes for the REST API and
MCP tools. They are separate from the ORM models to maintain clean
boundaries between the API and database layers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    import uuid
    from datetime import datetime
    from decimal import Decimal

# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------


class CreateEscrowRequest(BaseModel):
    """Request body for creating a new escrow contract."""

    buyer_wallet: str = Field(
        ...,
        min_length=42,
        max_length=42,
        description="EVM wallet address of the buyer agent (0x-prefixed, 42 chars)",
        examples=["0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"],
    )
    amount_usdc: Decimal = Field(
        ...,
        gt=0,
        decimal_places=6,
        description="Escrow amount in USDC",
        examples=[100.0],
    )
    description: str = Field(
        ...,
        min_length=10,
        max_length=5000,
        description="Human-readable description of the task",
        examples=["Write a Python script that calculates the 10th Fibonacci number"],
    )
    requirements_schema: dict | None = Field(
        default=None,
        description="JSON Schema that the worker's output must validate against",
    )
    verification_logic: dict = Field(
        ...,
        description=(
            'Verification config. Must include "type" key. '
            'Examples: {"type": "code_execution", "timeout": 30, "expected_output": "55"}, '
            '{"type": "semantic", "criteria": "The poem must rhyme"}, '
            '{"type": "schema"}'
        ),
        examples=[{"type": "code_execution", "timeout": 30, "expected_output": "55"}],
    )
    max_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum verification attempts before marking FAILED",
    )
    idempotency_key: str | None = Field(
        default=None,
        description="Optional idempotency key to prevent duplicate contract creation",
    )


class FundEscrowRequest(BaseModel):
    """Request body for recording that a contract has been funded on-chain."""

    tx_hash: str = Field(
        ...,
        min_length=66,
        max_length=66,
        description="Transaction hash of the on-chain funding (0x-prefixed)",
        examples=["0xabc123..."],
    )
    escrow_wallet_address: str = Field(
        ...,
        min_length=42,
        max_length=42,
        description="Wallet address holding the escrowed funds",
    )


class AcceptContractRequest(BaseModel):
    """Request body for a worker agent accepting a contract."""

    worker_wallet: str = Field(
        ...,
        min_length=42,
        max_length=42,
        description="EVM wallet address of the worker agent",
    )


class SubmitWorkRequest(BaseModel):
    """Request body for submitting work against a contract."""

    contract_id: uuid.UUID = Field(
        ...,
        description="UUID of the escrow contract",
    )
    content: str = Field(
        ...,
        min_length=1,
        max_length=100_000,
        description="The work payload (code, JSON, text)",
    )
    worker_wallet: str | None = Field(
        default=None,
        description="Worker wallet address (optional, for verification)",
    )


class RaiseDisputeRequest(BaseModel):
    """Request body for raising a dispute against a contract."""

    reason: str = Field(
        ...,
        min_length=10,
        max_length=2000,
        description="Detailed reason for the dispute",
    )
    raised_by: str = Field(
        ...,
        min_length=42,
        max_length=42,
        description="Wallet address of the party raising the dispute",
    )


# ---------------------------------------------------------------------------
# Response Schemas
# ---------------------------------------------------------------------------


class EscrowResponse(BaseModel):
    """Response schema for an escrow contract."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    buyer_wallet: str
    worker_wallet: str | None
    amount_usdc: Decimal
    status: str
    description: str | None
    requirements_schema: dict | None
    verification_logic: dict
    max_retries: int
    retry_count: int
    escrow_wallet_address: str | None
    funding_tx_hash: str | None
    settlement_tx_hash: str | None
    created_at: datetime
    updated_at: datetime


class WorkSubmissionResponse(BaseModel):
    """Response schema for a work submission."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_id: uuid.UUID
    payload: str
    submitted_by: str | None
    is_valid: bool | None
    verification_result: dict | None
    submitted_at: datetime


class EscrowEventResponse(BaseModel):
    """Response schema for an audit event."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    contract_id: uuid.UUID
    event_type: str
    old_status: str | None
    new_status: str
    actor: str
    metadata: dict | None = Field(default=None, alias="metadata_json")
    created_at: datetime


class ContractStatusResponse(BaseModel):
    """Lightweight status check response."""

    contract_id: uuid.UUID
    status: str
    retry_count: int
    max_retries: int
    allowed_events: list[str] = Field(
        description="State machine events that can fire from the current status"
    )


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "0.1.0"
    database: str = "unknown"
    redis: str = "unknown"
