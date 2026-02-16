"""CodeExecutionVerifier — runs submitted code in an E2B sandbox.

Use case: "Write a Python script that calculates the 10th Fibonacci number"
— worker submits code, system runs it in an isolated sandbox and checks
that it produces the expected output.

Verification flow:
    1. Spin up an E2B sandbox (isolated cloud VM, ~400ms cold start).
    2. Run the submitted Python code.
    3. Check: Did it exit with code 0? Does stdout contain expected_output?
    4. Return pass/fail with full stdout/stderr logs.

Security:
    - E2B sandboxes are fully isolated (separate VM per execution).
    - Network access, filesystem, and system calls are sandboxed.
    - Timeout enforced both at E2B level and our application level.
    - Malicious code (rm -rf /, network exfil) fails safely.
"""

from __future__ import annotations

from tenacity import retry, stop_after_attempt, wait_exponential

from agentic_clearinghouse.config import get_settings
from agentic_clearinghouse.domain.verifier_protocol import (
    VerificationRequest,
    VerificationResult,
)
from agentic_clearinghouse.logging_config import get_logger

logger = get_logger(__name__)


class CodeExecutionVerifier:
    """Verifier that runs code in an E2B sandbox and checks output."""

    def __init__(self, api_key: str | None = None, timeout: int | None = None) -> None:
        """Initialize with optional overrides (defaults come from config)."""
        self._api_key = api_key
        self._timeout = timeout

    def _get_config(self) -> dict:
        """Resolve configuration from overrides or settings."""
        settings = get_settings()
        return {
            "api_key": self._api_key if self._api_key is not None else settings.e2b_api_key,
            "timeout": self._timeout if self._timeout is not None else settings.e2b_timeout_seconds,
        }

    async def verify(self, request: VerificationRequest) -> VerificationResult:
        """Run the submitted code in an E2B sandbox and verify output.

        Args:
            request: Must have:
                - payload: Python source code to execute.
                - verification_config: Optional keys:
                    - "timeout" (int): Override timeout in seconds.
                    - "expected_output" (str): Expected stdout content.
                    - "expected_file" (str): Expected file to be created.

        Returns:
            VerificationResult with execution logs and pass/fail status.
        """
        config = self._get_config()
        v_config = request.verification_config
        timeout = v_config.get("timeout", config["timeout"])
        expected_output = v_config.get("expected_output", "").strip()

        if not config["api_key"]:
            return VerificationResult(
                is_valid=False,
                details="E2B API key not configured.",
                error="MISSING_E2B_API_KEY",
            )

        logger.info(
            "verifier.code_execution.start",
            contract_id=request.contract_id,
            timeout=timeout,
            has_expected_output=bool(expected_output),
        )

        try:
            stdout, stderr, exit_code = await self._run_in_sandbox(
                code=request.payload,
                api_key=config["api_key"],
                timeout=timeout,
            )

            logs = {
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
                "timeout": timeout,
                "expected_output": expected_output,
            }

            # --- Check 1: Exit code must be 0 ---
            if exit_code != 0:
                logger.info(
                    "verifier.code_execution.nonzero_exit",
                    contract_id=request.contract_id,
                    exit_code=exit_code,
                )
                return VerificationResult(
                    is_valid=False,
                    details=f"Code exited with non-zero exit code: {exit_code}",
                    logs=logs,
                )

            # --- Check 2: Expected output (if specified) ---
            if expected_output:
                stdout_stripped = stdout.strip()
                if expected_output in stdout_stripped:
                    logger.info(
                        "verifier.code_execution.passed",
                        contract_id=request.contract_id,
                    )
                    return VerificationResult(
                        is_valid=True,
                        score=1.0,
                        details=(
                            f"Code executed successfully. "
                            f"Expected output '{expected_output}' found in stdout."
                        ),
                        logs=logs,
                    )
                else:
                    logger.info(
                        "verifier.code_execution.output_mismatch",
                        contract_id=request.contract_id,
                        actual=stdout_stripped[:200],
                        expected=expected_output,
                    )
                    return VerificationResult(
                        is_valid=False,
                        details=(
                            f"Code ran successfully but output doesn't match. "
                            f"Expected '{expected_output}' in stdout, "
                            f"got: '{stdout_stripped[:200]}'"
                        ),
                        logs=logs,
                    )

            # --- No expected_output: just check exit code 0 ---
            logger.info(
                "verifier.code_execution.passed_no_output_check",
                contract_id=request.contract_id,
            )
            return VerificationResult(
                is_valid=True,
                score=1.0,
                details="Code executed successfully with exit code 0.",
                logs=logs,
            )

        except TimeoutError:
            logger.warning(
                "verifier.code_execution.timeout",
                contract_id=request.contract_id,
                timeout=timeout,
            )
            return VerificationResult(
                is_valid=False,
                details=f"Code execution timed out after {timeout} seconds.",
                error="EXECUTION_TIMEOUT",
                logs={"timeout": timeout},
            )
        except Exception as exc:
            logger.exception(
                "verifier.code_execution.error",
                contract_id=request.contract_id,
            )
            return VerificationResult(
                is_valid=False,
                details=f"Sandbox execution failed: {exc}",
                error="SANDBOX_ERROR",
                logs={"exception": str(exc)},
            )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        reraise=True,
    )
    async def _run_in_sandbox(
        self,
        code: str,
        api_key: str,
        timeout: int,
    ) -> tuple[str, str, int]:
        """Execute code in an E2B sandbox and return (stdout, stderr, exit_code).

        Uses the E2B Code Interpreter SDK. The sandbox is automatically
        destroyed when the context manager exits.
        """
        from e2b_code_interpreter import AsyncSandbox

        stdout_parts: list[str] = []
        stderr_parts: list[str] = []

        sandbox = await AsyncSandbox.create(api_key=api_key, timeout=timeout)
        try:
            execution = await sandbox.run_code(
                code,
                on_stdout=lambda msg: stdout_parts.append(msg.line),
                on_stderr=lambda msg: stderr_parts.append(msg.line),
                timeout=timeout,
            )

            stdout = "\n".join(stdout_parts)
            stderr = "\n".join(stderr_parts)

            # E2B execution.error is set if the code raised an exception
            if execution.error:
                return stdout, f"{stderr}\n{execution.error.name}: {execution.error.value}", 1

            return stdout, stderr, 0
        finally:
            await sandbox.kill()
