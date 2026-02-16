"""Shared test fixtures for the Agentic Clearinghouse test suite.

Provides:
    - In-memory or test database sessions
    - Factory functions for creating test data
    - Async test support via pytest-asyncio
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

# ---------------------------------------------------------------------------
# Domain Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_contract_data() -> dict:
    """Return a valid contract creation data dict."""
    return {
        "buyer_wallet": "0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18",
        "amount_usdc": Decimal("100.000000"),
        "description": "Write a Python script that calculates the 10th Fibonacci number",
        "requirements_schema": None,
        "verification_logic": {
            "type": "code_execution",
            "timeout": 30,
            "expected_output": "55",
        },
        "max_retries": 3,
    }


@pytest.fixture
def sample_contract_id() -> uuid.UUID:
    """Return a deterministic UUID for testing."""
    return uuid.UUID("12345678-1234-5678-1234-567812345678")
