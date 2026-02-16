"""Unit tests for the CodeExecutionVerifier.

Uses mocked E2B sandbox to test logic without hitting the real API.
Integration tests with a real sandbox are in test_integration.py.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from agentic_clearinghouse.domain.verifier_protocol import VerificationRequest
from agentic_clearinghouse.verifiers.code_execution import CodeExecutionVerifier


def _make_request(
    payload: str = 'print("55")',
    expected_output: str = "55",
    timeout: int = 30,
) -> VerificationRequest:
    return VerificationRequest(
        contract_id="test-contract-003",
        payload=payload,
        verification_config={
            "type": "code_execution",
            "timeout": timeout,
            "expected_output": expected_output,
        },
    )


class TestCodeExecutionHappyPath:
    @pytest.mark.asyncio
    async def test_correct_output_passes(self) -> None:
        verifier = CodeExecutionVerifier(api_key="test-key")

        with patch.object(
            verifier, "_run_in_sandbox", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = ("55", "", 0)
            result = await verifier.verify(_make_request())

        assert result.is_valid is True
        assert result.score == 1.0
        assert "55" in result.details

    @pytest.mark.asyncio
    async def test_no_expected_output_passes_on_exit_zero(self) -> None:
        verifier = CodeExecutionVerifier(api_key="test-key")

        with patch.object(
            verifier, "_run_in_sandbox", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = ("hello world", "", 0)
            result = await verifier.verify(
                _make_request(expected_output="", payload='print("hello world")')
            )

        assert result.is_valid is True
        assert "exit code 0" in result.details


class TestCodeExecutionFailures:
    @pytest.mark.asyncio
    async def test_nonzero_exit_code_fails(self) -> None:
        verifier = CodeExecutionVerifier(api_key="test-key")

        with patch.object(
            verifier, "_run_in_sandbox", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = ("", "NameError: name 'x' is not defined", 1)
            result = await verifier.verify(_make_request())

        assert result.is_valid is False
        assert "non-zero exit code" in result.details
        assert result.logs["exit_code"] == 1

    @pytest.mark.asyncio
    async def test_wrong_output_fails(self) -> None:
        verifier = CodeExecutionVerifier(api_key="test-key")

        with patch.object(
            verifier, "_run_in_sandbox", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = ("42", "", 0)
            result = await verifier.verify(_make_request(expected_output="55"))

        assert result.is_valid is False
        assert "doesn't match" in result.details

    @pytest.mark.asyncio
    async def test_timeout_fails(self) -> None:
        verifier = CodeExecutionVerifier(api_key="test-key")

        with patch.object(
            verifier, "_run_in_sandbox", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = TimeoutError("Sandbox timed out")
            result = await verifier.verify(_make_request())

        assert result.is_valid is False
        assert result.error == "EXECUTION_TIMEOUT"

    @pytest.mark.asyncio
    async def test_sandbox_exception_fails(self) -> None:
        verifier = CodeExecutionVerifier(api_key="test-key")

        with patch.object(
            verifier, "_run_in_sandbox", new_callable=AsyncMock
        ) as mock_run:
            mock_run.side_effect = RuntimeError("E2B API error")
            result = await verifier.verify(_make_request())

        assert result.is_valid is False
        assert result.error == "SANDBOX_ERROR"


class TestCodeExecutionConfig:
    @pytest.mark.asyncio
    async def test_missing_api_key_fails(self) -> None:
        verifier = CodeExecutionVerifier(api_key="")  # explicitly empty
        result = await verifier.verify(_make_request())

        assert result.is_valid is False
        assert result.error == "MISSING_E2B_API_KEY"

    @pytest.mark.asyncio
    async def test_expected_output_partial_match(self) -> None:
        """Expected output uses 'in' check, not exact match."""
        verifier = CodeExecutionVerifier(api_key="test-key")

        with patch.object(
            verifier, "_run_in_sandbox", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = ("The answer is 55, hooray!", "", 0)
            result = await verifier.verify(_make_request(expected_output="55"))

        assert result.is_valid is True


class TestCodeExecutionMalicious:
    """Test that malicious code scenarios are handled safely."""

    @pytest.mark.asyncio
    async def test_malicious_code_returns_nonzero(self) -> None:
        """If malicious code fails in sandbox, we get nonzero exit."""
        verifier = CodeExecutionVerifier(api_key="test-key")

        with patch.object(
            verifier, "_run_in_sandbox", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = (
                "",
                "PermissionError: Operation not permitted",
                1,
            )
            result = await verifier.verify(
                _make_request(payload='import os; os.system("rm -rf /")')
            )

        assert result.is_valid is False
        assert result.logs["exit_code"] == 1
