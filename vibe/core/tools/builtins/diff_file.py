from __future__ import annotations

import asyncio
from pathlib import Path
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


class DiffHunk(BaseModel):
    start_line: int
    end_line: int
    old_lines: list[str] = Field(default_factory=list)
    new_lines: list[str] = Field(default_factory=list)
    header: str = ""


class DiffFileArgs(BaseModel):
    path: str = Field(description="Path to file to diff.")
    staged: bool = Field(
        default=False,
        description="Show staged changes (git add'd) vs unstaged.",
    )
    context_lines: int = Field(
        default=3,
        description="Number of context lines around changes.",
    )


class DiffFileResult(BaseModel):
    path: str
    has_changes: bool = False
    additions: int = 0
    deletions: int = 0
    hunks: list[DiffHunk] = Field(default_factory=list)
    diff_text: str = ""
    summary: str = ""


class DiffFileToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_diff_size: int = Field(default=50000, description="Max diff output size.")


class DiffFileState(BaseToolState):
    pass


class DiffFile(
    BaseTool[DiffFileArgs, DiffFileResult, DiffFileToolConfig, DiffFileState],
    ToolUIData[DiffFileArgs, DiffFileResult],
):
    description: ClassVar[str] = (
        "Show diff/changes for a specific file. "
        "Use to preview modifications before committing or to understand changes."
    )

    @final
    async def run(self, args: DiffFileArgs) -> DiffFileResult:
        workdir = self.config.effective_workdir
        file_path = self._prepare_path(args.path)

        is_git = await self._is_git_repo(workdir)
        if not is_git:
            raise ToolError("Not a git repository")

        diff_text = await self._get_diff(workdir, file_path, args.staged, args.context_lines)

        if not diff_text.strip():
            return DiffFileResult(
                path=str(file_path),
                has_changes=False,
                summary="No changes",
            )

        additions, deletions = self._count_changes(diff_text)
        hunks = self._parse_hunks(diff_text)

        summary = f"+{additions}/-{deletions} in {len(hunks)} hunk(s)"

        return DiffFileResult(
            path=str(file_path),
            has_changes=True,
            additions=additions,
            deletions=deletions,
            hunks=hunks,
            diff_text=diff_text[:self.config.max_diff_size],
            summary=summary,
        )

    def _prepare_path(self, path_str: str) -> Path:
        file_path = Path(path_str).expanduser()
        if not file_path.is_absolute():
            file_path = self.config.effective_workdir / file_path
        return file_path.resolve()

    async def _is_git_repo(self, workdir: Path) -> bool:
        proc = await asyncio.create_subprocess_exec(
            "git", "rev-parse", "--git-dir",
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0

    async def _get_diff(
        self, workdir: Path, file_path: Path, staged: bool, context: int
    ) -> str:
        cmd = ["git", "diff"]
        if staged:
            cmd.append("--cached")
        cmd.extend([f"-U{context}", "--", str(file_path)])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")

    def _count_changes(self, diff_text: str) -> tuple[int, int]:
        additions = 0
        deletions = 0

        for line in diff_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                additions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1

        return additions, deletions

    def _parse_hunks(self, diff_text: str) -> list[DiffHunk]:
        hunks: list[DiffHunk] = []
        current_hunk: DiffHunk | None = None

        import re
        hunk_header_re = re.compile(r"^@@ -(\d+),?\d* \+(\d+),?\d* @@(.*)$")

        for line in diff_text.splitlines():
            match = hunk_header_re.match(line)
            if match:
                if current_hunk:
                    hunks.append(current_hunk)

                current_hunk = DiffHunk(
                    start_line=int(match.group(2)),
                    end_line=int(match.group(2)),
                    header=match.group(3).strip(),
                )
            elif current_hunk:
                if line.startswith("-") and not line.startswith("---"):
                    current_hunk.old_lines.append(line[1:])
                elif line.startswith("+") and not line.startswith("+++"):
                    current_hunk.new_lines.append(line[1:])
                    current_hunk.end_line += 1
                elif not line.startswith("\\"):
                    current_hunk.end_line += 1

        if current_hunk:
            hunks.append(current_hunk)

        return hunks

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, DiffFileArgs):
            return ToolCallDisplay(summary="diff_file")

        staged = " (staged)" if event.args.staged else ""
        return ToolCallDisplay(
            summary=f"diff: {event.args.path}{staged}",
            details={"path": event.args.path, "staged": event.args.staged},
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, DiffFileResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        if not result.has_changes:
            return ToolResultDisplay(success=True, message="No changes")

        lines = [
            f"📊 {result.summary}",
            "",
        ]

        for i, hunk in enumerate(result.hunks[:5], 1):
            lines.append(f"Hunk {i} (L{hunk.start_line}):")
            for line in hunk.old_lines[:3]:
                lines.append(f"  - {line}")
            for line in hunk.new_lines[:3]:
                lines.append(f"  + {line}")
            if len(hunk.old_lines) > 3 or len(hunk.new_lines) > 3:
                lines.append("  ...")

        if len(result.hunks) > 5:
            lines.append(f"\n... and {len(result.hunks) - 5} more hunks")

        return ToolResultDisplay(
            success=True,
            message=result.summary,
            details={"diff": result.diff_text[:2000]},
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Getting diff"
