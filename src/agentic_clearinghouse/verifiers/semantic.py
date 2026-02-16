"""SemanticVerifier — uses an LLM judge to evaluate subjective work quality.

Use case: "Write a tweet about AI" — worker submits text, the LLM judge
evaluates whether it meets the buyer's criteria.

Verification flow:
    1. Build a structured judge prompt with the criteria and submitted work.
    2. Call the LLM via LiteLLM (supports Gemini, GPT-4o, Llama, etc.)
    3. Parse the LLM's TRUE/FALSE verdict.
    4. Return pass/fail with the LLM's reasoning.

The judge prompt is designed to be strict and deterministic:
    - Temperature is set to 0.0
    - The LLM must answer with a structured format
    - Ambiguous answers are treated as FAIL
"""

from __future__ import annotations

import litellm
from tenacity import retry, stop_after_attempt, wait_exponential

from agentic_clearinghouse.config import get_settings
from agentic_clearinghouse.domain.verifier_protocol import (
    VerificationRequest,
    VerificationResult,
)
from agentic_clearinghouse.logging_config import get_logger

logger = get_logger(__name__)

# --- Judge System Prompt ---
JUDGE_SYSTEM_PROMPT = """You are an impartial, strict verification judge for an AI escrow system.

Your job is to determine whether submitted work meets the specified criteria.
You must be OBJECTIVE and STRICT. If there is any ambiguity, err on the side of FAILING.

You MUST respond in EXACTLY this format (no extra text before or after):

VERDICT: TRUE or FALSE
SCORE: a number from 0.0 to 1.0
REASONING: one paragraph explaining your decision

Rules:
- VERDICT must be exactly "TRUE" or "FALSE" (no "MAYBE", "PARTIAL", etc.)
- SCORE 1.0 = perfect, 0.0 = completely wrong
- Be concise but thorough in REASONING
"""

JUDGE_USER_TEMPLATE = """## Criteria
{criteria}

## Submitted Work
{payload}

Evaluate whether the submitted work meets the criteria above."""


class SemanticVerifier:
    """Verifier that uses an LLM judge to evaluate subjective work quality."""

    def __init__(
        self,
        model: str | None = None,
        fallback_models: list[str] | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> None:
        """Initialize with optional overrides (defaults come from config)."""
        self._model = model
        self._fallback_models = fallback_models
        self._max_tokens = max_tokens
        self._temperature = temperature

    def _get_model_config(self) -> dict:
        """Resolve model configuration from overrides or settings."""
        settings = get_settings()
        return {
            "model": self._model or settings.litellm_model,
            "fallback_models": self._fallback_models or settings.litellm_fallback_model_list,
            "max_tokens": self._max_tokens or settings.litellm_max_tokens,
            "temperature": (
                self._temperature if self._temperature is not None else settings.litellm_temperature
            ),
        }

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        """Evaluate the payload against semantic criteria using an LLM judge.

        Args:
            request: Must have:
                - payload: The submitted work to evaluate.
                - verification_config: Must contain "criteria" key.

        Returns:
            VerificationResult with is_valid based on the LLM's verdict.
        """
        criteria = request.verification_config.get("criteria", "")
        if not criteria:
            return VerificationResult(
                is_valid=False,
                details="No 'criteria' field in verification_logic.",
                error="MISSING_CRITERIA",
            )

        logger.info(
            "verifier.semantic.start",
            contract_id=request.contract_id,
            criteria_preview=criteria[:100],
        )

        try:
            llm_response = await self._call_llm(criteria, request.payload)
            verdict, score, reasoning = self._parse_response(llm_response)

            logger.info(
                "verifier.semantic.result",
                contract_id=request.contract_id,
                verdict=verdict,
                score=score,
            )

            return VerificationResult(
                is_valid=verdict,
                score=score,
                details=reasoning,
                logs={
                    "llm_response": llm_response,
                    "criteria": criteria,
                    "model": self._get_model_config()["model"],
                },
            )

        except Exception as exc:
            logger.exception(
                "verifier.semantic.error",
                contract_id=request.contract_id,
            )
            return VerificationResult(
                is_valid=False,
                details=f"LLM judge failed: {exc}",
                error="LLM_JUDGE_ERROR",
                logs={"exception": str(exc)},
            )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _call_llm(self, criteria: str, payload: str) -> str:
        """Call the LLM via LiteLLM with retry logic.

        Uses tenacity for exponential backoff on transient failures.
        """
        config = self._get_model_config()

        user_message = JUDGE_USER_TEMPLATE.format(
            criteria=criteria,
            payload=payload,
        )

        response = await litellm.acompletion(
            model=config["model"],
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            max_tokens=config["max_tokens"],
            temperature=config["temperature"],
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("LLM returned empty response")

        return content.strip()

    def _parse_response(self, response: str) -> tuple[bool, float, str]:
        """Parse the structured LLM judge response.

        Expected format:
            VERDICT: TRUE
            SCORE: 0.85
            REASONING: The work meets all criteria because...

        Returns:
            (verdict_bool, score_float, reasoning_string)
        """
        verdict = False
        score = 0.0
        reasoning = ""

        for line in response.split("\n"):
            line = line.strip()
            if line.upper().startswith("VERDICT:"):
                verdict_str = line.split(":", 1)[1].strip().upper()
                verdict = verdict_str == "TRUE"
            elif line.upper().startswith("SCORE:"):
                try:
                    score = float(line.split(":", 1)[1].strip())
                    score = max(0.0, min(1.0, score))  # Clamp to [0, 1]
                except (ValueError, IndexError):
                    score = 0.0
            elif line.upper().startswith("REASONING:"):
                reasoning = line.split(":", 1)[1].strip()

        # If reasoning spans multiple lines after the label
        if not reasoning and "REASONING:" in response.upper():
            parts = response.upper().split("REASONING:", 1)
            if len(parts) > 1:
                # Get everything after REASONING: from the original (case-preserved) text
                idx = response.upper().index("REASONING:") + len("REASONING:")
                reasoning = response[idx:].strip()

        if not reasoning:
            reasoning = (
                f"Could not parse structured reasoning from LLM response. Raw: {response[:200]}"
            )

        return verdict, score, reasoning
