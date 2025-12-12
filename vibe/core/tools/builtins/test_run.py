from __future__ import annotations

import asyncio
from pathlib import Path
import re
import sys
from typing import TYPE_CHECKING, ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import (
    BaseTool,
    BaseToolConfig,
    BaseToolState,
    ToolError,
    ToolPermission,
)
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData

if TYPE_CHECKING:
    from vibe.core.types import ToolCallEvent, ToolResultEvent


MAX_FAILED_TESTS_DISPLAY = 5


class TestResult(BaseModel):
    __test__ = False
    name: str
    status: str  # "passed", "failed", "error", "skipped"
    duration: float | None = None
    error_message: str | None = None


class TestRunArgs(BaseModel):
    __test__ = False
    path: str = Field(
        default=".",
        description="Path to test file or directory. Defaults to current directory.",
    )
    pattern: str | None = Field(
        default=None,
        description="Pattern to filter tests (e.g., 'test_auth' or '*login*').",
    )
    verbose: bool = Field(
        default=True, description="Show verbose output with individual test results."
    )
    fail_fast: bool = Field(default=False, description="Stop on first failure.")
    max_tests: int = Field(
        default=50, description="Maximum number of test results to return."
    )


class TestRunResult(BaseModel):
    __test__ = False
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    total: int = 0
    duration: float = 0.0
    tests: list[TestResult] = Field(default_factory=list)
    failed_tests: list[TestResult] = Field(default_factory=list)
    output: str = ""
    success: bool = True
    summary: str = ""


class TestRunToolConfig(BaseToolConfig):
    __test__ = False
    permission: ToolPermission = ToolPermission.ASK
    timeout: int = Field(default=120, description="Test timeout in seconds.")
    max_output: int = Field(default=10000, description="Max output characters.")


class TestRunState(BaseToolState):
    __test__ = False
    last_run_results: TestRunResult | None = None


class TestRun(
    BaseTool[TestRunArgs, TestRunResult, TestRunToolConfig, TestRunState],
    ToolUIData[TestRunArgs, TestRunResult],
):
    __test__ = False
    description: ClassVar[str] = (
        "Run pytest tests and return structured results. "
        "Use this to verify code changes, run specific tests, or check test coverage."
    )

    @final
    async def run(self, args: TestRunArgs) -> TestRunResult:
        test_path = self._prepare_path(args)
        cmd = self._build_command(args, test_path)

        stdout, stderr, returncode, duration = await self._run_pytest(cmd)

        result = self._parse_output(
            stdout, stderr, returncode, duration, args.max_tests
        )
        self.state.last_run_results = result

        return result

    def _prepare_path(self, args: TestRunArgs) -> Path:
        path_str = args.path.strip() or "."
        test_path = Path(path_str).expanduser()

        if not test_path.is_absolute():
            test_path = self.config.effective_workdir / test_path

        return test_path.resolve()

    def _build_command(self, args: TestRunArgs, test_path: Path) -> list[str]:
        cmd = [sys.executable, "-m", "pytest", str(test_path)]

        if args.verbose:
            cmd.append("-v")

        if args.fail_fast:
            cmd.append("-x")

        if args.pattern:
            cmd.extend(["-k", args.pattern])

        cmd.append("--tb=short")
        cmd.append(f"--timeout={self.config.timeout}")

        return cmd

    async def _run_pytest(self, cmd: list[str]) -> tuple[str, str, int, float]:
        import time

        start = time.time()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self.config.effective_workdir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=self.config.timeout + 10
                )
            except TimeoutError:
                proc.kill()
                await proc.wait()
                raise ToolError(f"Tests timed out after {self.config.timeout}s")

            duration = time.time() - start
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")

            stdout = stdout[: self.config.max_output]
            stderr = stderr[: self.config.max_output // 2]

            return stdout, stderr, proc.returncode or 0, duration

        except FileNotFoundError:
            raise ToolError("pytest not found. Install with: pip install pytest")

    def _parse_output(
        self, stdout: str, stderr: str, returncode: int, duration: float, max_tests: int
    ) -> TestRunResult:
        tests, failed_tests, counts = self._parse_test_lines(stdout, max_tests)

        # Override counts with summary info if available
        summary_counts = self._parse_summary(stdout)
        if summary_counts:
            counts.update(summary_counts)

        passed = counts["passed"]
        failed = counts["failed"]
        errors = counts["errors"]
        skipped = counts["skipped"]

        total = passed + failed + errors + skipped
        success = returncode == 0 and failed == 0 and errors == 0

        summary = f"{'✅' if success else '❌'} {passed} passed"
        if failed:
            summary += f", {failed} failed"
        if errors:
            summary += f", {errors} errors"
        if skipped:
            summary += f", {skipped} skipped"
        summary += f" in {duration:.1f}s"

        return TestRunResult(
            passed=passed,
            failed=failed,
            errors=errors,
            skipped=skipped,
            total=total,
            duration=duration,
            tests=tests,
            failed_tests=failed_tests,
            output=stdout + stderr,
            success=success,
            summary=summary,
        )

    def _parse_test_lines(
        self, stdout: str, max_tests: int
    ) -> tuple[list[TestResult], list[TestResult], dict[str, int]]:
        tests: list[TestResult] = []
        failed_tests: list[TestResult] = []
        counts = {"passed": 0, "failed": 0, "errors": 0, "skipped": 0}

        test_pattern = re.compile(
            r"^([\w/\.]+::[\w]+(?:::[\w]+)?)\s+(PASSED|FAILED|ERROR|SKIPPED)",
            re.MULTILINE,
        )

        for match in test_pattern.finditer(stdout):
            if len(tests) >= max_tests:
                break

            name = match.group(1)
            status = match.group(2).lower()

            test = TestResult(name=name, status=status)
            tests.append(test)

            if status == "passed":
                counts["passed"] += 1
            elif status == "failed":
                counts["failed"] += 1
                failed_tests.append(test)
            elif status == "error":
                counts["errors"] += 1
                failed_tests.append(test)
            elif status == "skipped":
                counts["skipped"] += 1

        return tests, failed_tests, counts

    def _parse_summary(self, stdout: str) -> dict[str, int] | None:
        counts = {}
        summary_match = re.search(
            r"=+\s*(\d+)\s+passed.*?(\d+)?\s*failed.*?in\s+([\d.]+)s",
            stdout,
            re.IGNORECASE,
        )
        if summary_match:
            counts["passed"] = int(summary_match.group(1))
            counts["failed"] = int(summary_match.group(2) or 0)
            return counts

        alt_summary = re.search(r"=+\s*([\d\w, ]+)\s+in\s+([\d.]+)s\s*=+", stdout)
        if alt_summary:
            status_text = alt_summary.group(1)
            for status in ["passed", "failed", "skipped", "error"]:
                m = re.search(rf"(\d+)\s+{status}", status_text)
                if m:
                    counts[status + "s" if status == "error" else status] = int(
                        m.group(1)
                    )
            return counts

        return None

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, TestRunArgs):
            return ToolCallDisplay(summary="test_run")

        path = event.args.path or "."
        pattern = f" -k '{event.args.pattern}'" if event.args.pattern else ""
        return ToolCallDisplay(
            summary=f"pytest {path}{pattern}",
            details={
                "path": path,
                "pattern": event.args.pattern,
                "fail_fast": event.args.fail_fast,
            },
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, TestRunResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        lines = [result.summary]

        if result.failed_tests:
            lines.append("\n❌ Failed Tests:")
            for test in result.failed_tests[:MAX_FAILED_TESTS_DISPLAY]:
                lines.append(f"  • {test.name}")
            if len(result.failed_tests) > MAX_FAILED_TESTS_DISPLAY:
                lines.append(
                    f"  ... and {len(result.failed_tests) - MAX_FAILED_TESTS_DISPLAY} more"
                )

        return ToolResultDisplay(
            success=result.success,
            message=result.summary,
            details={"output": "\n".join(lines)},
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Running tests"
