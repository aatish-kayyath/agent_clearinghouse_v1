"""Integration tests for verifiers against REAL external services.

These tests hit real APIs (E2B, Gemini) and require:
    - E2B_API_KEY set in .env
    - GEMINI_API_KEY set in .env

Run with:
    uv run pytest tests/test_verifiers/test_integration.py -v -s

The -s flag shows stdout so you can see real API responses.
These are marked with @pytest.mark.integration so they can be skipped
in CI with: pytest -m "not integration"
"""

from __future__ import annotations

import os

import pytest

from agentic_clearinghouse.domain.verifier_protocol import VerificationRequest
from agentic_clearinghouse.verifiers.code_execution import CodeExecutionVerifier
from agentic_clearinghouse.verifiers.semantic import SemanticVerifier

# Skip all tests in this module if keys are missing
pytestmark = pytest.mark.integration

E2B_KEY = os.environ.get("E2B_API_KEY", "")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")


# ============================================================
# E2B Code Execution Integration Tests
# ============================================================


@pytest.mark.skipif(not E2B_KEY, reason="E2B_API_KEY not set")
class TestE2BIntegration:
    """Test CodeExecutionVerifier against real E2B sandbox."""

    @pytest.mark.asyncio
    async def test_fibonacci_happy_path(self) -> None:
        """Scenario A: Worker writes correct Fibonacci code."""
        verifier = CodeExecutionVerifier(api_key=E2B_KEY)

        fibonacci_code = '''
def fibonacci(n):
    if n <= 1:
        return n
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b

print(fibonacci(10))
'''
        request = VerificationRequest(
            contract_id="integration-fib-001",
            payload=fibonacci_code,
            verification_config={
                "type": "code_execution",
                "timeout": 30,
                "expected_output": "55",
            },
        )

        result = await verifier.verify(request)

        print(f"\n  stdout: {result.logs.get('stdout', '')}")
        print(f"  stderr: {result.logs.get('stderr', '')}")
        print(f"  is_valid: {result.is_valid}")
        print(f"  details: {result.details}")

        assert result.is_valid is True
        assert result.score == 1.0

    @pytest.mark.asyncio
    async def test_syntax_error_fails(self) -> None:
        """Worker submits code with a syntax error."""
        verifier = CodeExecutionVerifier(api_key=E2B_KEY)

        bad_code = "def broken(\n  print('oops')"

        request = VerificationRequest(
            contract_id="integration-syntax-001",
            payload=bad_code,
            verification_config={
                "type": "code_execution",
                "timeout": 15,
                "expected_output": "55",
            },
        )

        result = await verifier.verify(request)

        print(f"\n  is_valid: {result.is_valid}")
        print(f"  details: {result.details}")
        print(f"  stderr: {result.logs.get('stderr', '')[:200]}")

        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_malicious_code_sandboxed(self) -> None:
        """Scenario C: Worker tries to run malicious code (rm -rf /)."""
        verifier = CodeExecutionVerifier(api_key=E2B_KEY)

        malicious_code = '''
import os
try:
    os.system("rm -rf /")
    print("still alive")
except Exception as e:
    print(f"blocked: {e}")
'''
        request = VerificationRequest(
            contract_id="integration-malicious-001",
            payload=malicious_code,
            verification_config={
                "type": "code_execution",
                "timeout": 15,
                "expected_output": "calculator_result",
            },
        )

        result = await verifier.verify(request)

        print(f"\n  is_valid: {result.is_valid}")
        print(f"  stdout: {result.logs.get('stdout', '')}")
        print(f"  stderr: {result.logs.get('stderr', '')[:300]}")

        # The code may "run" in the sandbox but won't produce expected output
        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_wrong_output_fails(self) -> None:
        """Worker submits working code but wrong answer."""
        verifier = CodeExecutionVerifier(api_key=E2B_KEY)

        wrong_code = "print(42)"  # Expected 55

        request = VerificationRequest(
            contract_id="integration-wrong-001",
            payload=wrong_code,
            verification_config={
                "type": "code_execution",
                "timeout": 15,
                "expected_output": "55",
            },
        )

        result = await verifier.verify(request)

        print(f"\n  is_valid: {result.is_valid}")
        print(f"  details: {result.details}")

        assert result.is_valid is False
        assert "doesn't match" in result.details


# ============================================================
# Gemini Semantic Verification Integration Tests
# ============================================================


@pytest.mark.skipif(not GEMINI_KEY, reason="GEMINI_API_KEY not set")
class TestGeminiIntegration:
    """Test SemanticVerifier against real Gemini API."""

    @pytest.mark.asyncio
    async def test_tweet_meets_criteria(self) -> None:
        """Semantic check: good tweet passes."""
        verifier = SemanticVerifier(model="gemini/gemini-2.0-flash")

        request = VerificationRequest(
            contract_id="integration-semantic-001",
            payload=(
                "AI is transforming how we build software. "
                "From code generation to testing, the developer "
                "experience will never be the same. #AI #DevTools"
            ),
            verification_config={
                "type": "semantic",
                "criteria": (
                    "The text should be a tweet about AI and software development. "
                    "It should be under 280 characters and include at least one hashtag."
                ),
            },
        )

        result = await verifier.verify(request)

        print(f"\n  is_valid: {result.is_valid}")
        print(f"  score: {result.score}")
        print(f"  details: {result.details[:200]}")

        assert result.is_valid is True
        assert result.score is not None
        assert result.score > 0.5

    @pytest.mark.asyncio
    async def test_off_topic_fails(self) -> None:
        """Semantic check: completely off-topic text fails."""
        verifier = SemanticVerifier(model="gemini/gemini-2.0-flash")

        request = VerificationRequest(
            contract_id="integration-semantic-002",
            payload="I had a wonderful pasta dinner last night with extra parmesan.",
            verification_config={
                "type": "semantic",
                "criteria": (
                    "The text must be a technical explanation of quantum computing, "
                    "mentioning qubits and superposition."
                ),
            },
        )

        result = await verifier.verify(request)

        print(f"\n  is_valid: {result.is_valid}")
        print(f"  score: {result.score}")
        print(f"  details: {result.details[:200]}")

        assert result.is_valid is False

    @pytest.mark.asyncio
    async def test_rhyming_poem(self) -> None:
        """Semantic check: does this poem rhyme?"""
        verifier = SemanticVerifier(model="gemini/gemini-2.0-flash")

        request = VerificationRequest(
            contract_id="integration-semantic-003",
            payload=(
                "Roses are red,\n"
                "Violets are blue,\n"
                "AI writes the code,\n"
                "And debugs it too."
            ),
            verification_config={
                "type": "semantic",
                "criteria": "The text must be a short poem that rhymes (AABB or ABAB pattern).",
            },
        )

        result = await verifier.verify(request)

        print(f"\n  is_valid: {result.is_valid}")
        print(f"  score: {result.score}")
        print(f"  details: {result.details[:200]}")

        assert result.is_valid is True
