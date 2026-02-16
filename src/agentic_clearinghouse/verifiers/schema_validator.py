"""SchemaVerifier — validates submitted work against a JSON Schema.

Use case: "Extract email and phone from this website" — worker must return
JSON matching the buyer's schema exactly.

Verification flow:
    1. Parse the payload as JSON.
    2. Validate against the requirements_schema from the contract.
    3. Return pass/fail with detailed validation errors.

No external services required — this is a pure local check.
"""

from __future__ import annotations

import json

import jsonschema
from jsonschema import Draft7Validator

from agentic_clearinghouse.domain.verifier_protocol import (
    VerificationRequest,
    VerificationResult,
)
from agentic_clearinghouse.logging_config import get_logger

logger = get_logger(__name__)


class SchemaVerifier:
    """Verifier that checks JSON payloads against a JSON Schema."""

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        """Validate the payload against the requirements_schema.

        Args:
            request: Must have:
                - payload: A JSON string to validate.
                - requirements_schema: A JSON Schema dict to validate against.

        Returns:
            VerificationResult with is_valid=True if the payload matches the schema.
        """
        logger.info(
            "verifier.schema.start",
            contract_id=request.contract_id,
        )

        # --- Step 1: Check that a schema was provided ---
        if not request.requirements_schema:
            return VerificationResult(
                is_valid=False,
                details="No requirements_schema provided on the contract.",
                error="MISSING_SCHEMA",
            )

        # --- Step 2: Parse the payload as JSON ---
        try:
            parsed_payload = json.loads(request.payload)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning(
                "verifier.schema.json_parse_failed",
                contract_id=request.contract_id,
                error=str(exc),
            )
            return VerificationResult(
                is_valid=False,
                details=f"Payload is not valid JSON: {exc}",
                logs={"raw_payload_preview": request.payload[:500]},
                error="INVALID_JSON",
            )

        # --- Step 3: Validate against the JSON Schema ---
        try:
            # Use Draft7Validator for explicit schema validation
            validator = Draft7Validator(request.requirements_schema)
            errors = sorted(validator.iter_errors(parsed_payload), key=lambda e: list(e.path))

            if errors:
                error_details = []
                for err in errors:
                    error_details.append({
                        "path": list(err.path),
                        "message": err.message,
                        "schema_path": list(err.schema_path),
                    })

                logger.info(
                    "verifier.schema.validation_failed",
                    contract_id=request.contract_id,
                    error_count=len(errors),
                )

                return VerificationResult(
                    is_valid=False,
                    details=f"Schema validation failed with {len(errors)} error(s).",
                    logs={
                        "validation_errors": error_details,
                        "schema": request.requirements_schema,
                    },
                )

            # All good
            logger.info(
                "verifier.schema.passed",
                contract_id=request.contract_id,
            )

            return VerificationResult(
                is_valid=True,
                score=1.0,
                details="Payload successfully validated against the JSON Schema.",
                logs={
                    "schema": request.requirements_schema,
                    "parsed_payload": parsed_payload,
                },
            )

        except jsonschema.SchemaError as exc:
            # The schema itself is malformed
            logger.error(
                "verifier.schema.invalid_schema",
                contract_id=request.contract_id,
                error=str(exc),
            )
            return VerificationResult(
                is_valid=False,
                details=f"The requirements_schema itself is invalid: {exc.message}",
                error="INVALID_SCHEMA",
            )
        except Exception as exc:
            logger.exception(
                "verifier.schema.unexpected_error",
                contract_id=request.contract_id,
            )
            return VerificationResult(
                is_valid=False,
                details=f"Unexpected error during schema validation: {exc}",
                error="SCHEMA_VERIFIER_ERROR",
            )
