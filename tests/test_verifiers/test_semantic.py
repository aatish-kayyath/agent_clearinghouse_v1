"""Unit tests for the SemanticVerifier.

Uses mocked LiteLLM responses to test parsing and edge cases
without hitting a real LLM API.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_clearinghouse.domain.verifier_protocol import VerificationRequest
from agentic_clearinghouse.verifiers.semantic import SemanticVerifier


def _make_request(
    payload: str = "This is a great tweet about AI!",
    criteria: str = "The text should be a tweet about AI, under 280 characters.",
) -> VerificationRequest:
    return VerificationRequest(
        contract_id="test-contract-002",
        payload=payload,
        verification_config={"type": "semantic", "criteria": criteria},
    )


def _mock_llm_response(content: str) -> MagicMock:
    """Create a mock LiteLLM completion response."""
    mock_resp = MagicMock()
    mock_resp.choices = [MagicMock()]
    mock_resp.choices[0].message.content = content
    return mock_resp


class TestSemanticVerifierParsing:
    @pytest.mark.asyncio
    async def test_true_verdict_parsed(self) -> None:
        verifier = SemanticVerifier()
        llm_output = (
            "VERDICT: TRUE\n"
            "SCORE: 0.95\n"
            "REASONING: The tweet is concise, about AI, and under 280 characters."
        )

        with patch("agentic_clearinghouse.verifiers.semantic.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response(llm_output)
            )
            result = await verifier.verify(_make_request())

        assert result.is_valid is True
        assert result.score == 0.95
        assert "concise" in result.details

    @pytest.mark.asyncio
    async def test_false_verdict_parsed(self) -> None:
        verifier = SemanticVerifier()
        llm_output = (
            "VERDICT: FALSE\n"
            "SCORE: 0.2\n"
            "REASONING: The text is not related to AI at all."
        )

        with patch("agentic_clearinghouse.verifiers.semantic.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response(llm_output)
            )
            result = await verifier.verify(_make_request(payload="I love pizza"))

        assert result.is_valid is False
        assert result.score == 0.2

    @pytest.mark.asyncio
    async def test_score_clamped_to_bounds(self) -> None:
        verifier = SemanticVerifier()
        llm_output = "VERDICT: TRUE\nSCORE: 1.5\nREASONING: Excellent work."

        with patch("agentic_clearinghouse.verifiers.semantic.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response(llm_output)
            )
            result = await verifier.verify(_make_request())

        assert result.score == 1.0  # Clamped from 1.5

    @pytest.mark.asyncio
    async def test_malformed_response_defaults_to_fail(self) -> None:
        verifier = SemanticVerifier()
        llm_output = "I think it's pretty good but I'm not sure."

        with patch("agentic_clearinghouse.verifiers.semantic.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response(llm_output)
            )
            result = await verifier.verify(_make_request())

        # No VERDICT: TRUE found -> defaults to False
        assert result.is_valid is False
        assert result.score == 0.0


class TestSemanticVerifierErrors:
    @pytest.mark.asyncio
    async def test_missing_criteria(self) -> None:
        verifier = SemanticVerifier()
        request = VerificationRequest(
            contract_id="test",
            payload="some text",
            verification_config={"type": "semantic"},  # no criteria!
        )
        result = await verifier.verify(request)

        assert result.is_valid is False
        assert result.error == "MISSING_CRITERIA"

    @pytest.mark.asyncio
    async def test_llm_api_failure(self) -> None:
        verifier = SemanticVerifier()

        with patch("agentic_clearinghouse.verifiers.semantic.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                side_effect=Exception("API rate limit exceeded")
            )
            result = await verifier.verify(_make_request())

        assert result.is_valid is False
        assert result.error == "LLM_JUDGE_ERROR"
        assert "rate limit" in result.details

    @pytest.mark.asyncio
    async def test_empty_llm_response(self) -> None:
        verifier = SemanticVerifier()

        with patch("agentic_clearinghouse.verifiers.semantic.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(
                return_value=_mock_llm_response("")
            )
            # Empty content raises ValueError in _call_llm
            result = await verifier.verify(_make_request())

        assert result.is_valid is False


class TestResponseParsing:
    """Test the _parse_response method directly."""

    def test_standard_format(self) -> None:
        verifier = SemanticVerifier()
        verdict, score, reasoning = verifier._parse_response(
            "VERDICT: TRUE\nSCORE: 0.8\nREASONING: Looks good."
        )
        assert verdict is True
        assert score == 0.8
        assert reasoning == "Looks good."

    def test_case_insensitive_verdict(self) -> None:
        verifier = SemanticVerifier()
        verdict, _, _ = verifier._parse_response("verdict: true\nscore: 1.0\nreasoning: ok")
        assert verdict is True

    def test_false_verdict(self) -> None:
        verifier = SemanticVerifier()
        verdict, _, _ = verifier._parse_response("VERDICT: FALSE\nSCORE: 0.1\nREASONING: Bad")
        assert verdict is False

    def test_invalid_score_defaults_zero(self) -> None:
        verifier = SemanticVerifier()
        _, score, _ = verifier._parse_response("VERDICT: TRUE\nSCORE: not_a_number\nREASONING: ok")
        assert score == 0.0
