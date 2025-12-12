from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, final

from pydantic import BaseModel, Field

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolPermission
from vibe.core.tools.ui import ToolCallDisplay, ToolResultDisplay, ToolUIData

if TYPE_CHECKING:
    from vibe.core.types import ToolCallEvent, ToolResultEvent


class GitFileStatus(BaseModel):
    path: str
    status: str  # "modified", "added", "deleted", "renamed", "untracked"
    staged: bool = False


class GitStatusArgs(BaseModel):
    include_untracked: bool = Field(
        default=True, description="Include untracked files in output."
    )
    show_stash: bool = Field(default=False, description="Show stash entries.")


class GitStatusResult(BaseModel):
    is_git_repo: bool
    branch: str | None = None
    ahead: int = 0
    behind: int = 0
    staged: list[GitFileStatus] = Field(default_factory=list)
    unstaged: list[GitFileStatus] = Field(default_factory=list)
    untracked: list[str] = Field(default_factory=list)
    stash_count: int = 0
    has_conflicts: bool = False
    summary: str = ""


class GitStatusToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_files: int = Field(default=100, description="Max files to show.")


class GitStatusState(BaseToolState):
    pass


MAX_STATUS_DISPLAY = 10
MAX_UNTRACKED_DISPLAY = 5
MIN_SPLIT_PARTS = 2


class GitStatus(
    BaseTool[GitStatusArgs, GitStatusResult, GitStatusToolConfig, GitStatusState],
    ToolUIData[GitStatusArgs, GitStatusResult],
):
    description: ClassVar[str] = (
        "Get git repository status: branch, staged/unstaged changes, untracked files. "
        "Use this instead of 'git status' for structured output."
    )

    @final
    async def run(self, args: GitStatusArgs) -> GitStatusResult:
        workdir = self.config.effective_workdir

        is_git = await self._is_git_repo(workdir)
        if not is_git:
            return GitStatusResult(is_git_repo=False, summary="Not a git repository")

        branch, ahead, behind = await self._get_branch_info(workdir)
        staged = await self._get_staged_files(workdir)
        unstaged = await self._get_unstaged_files(workdir)
        untracked = (
            await self._get_untracked_files(workdir) if args.include_untracked else []
        )
        stash_count = await self._get_stash_count(workdir) if args.show_stash else 0
        has_conflicts = await self._has_conflicts(workdir)

        staged = staged[: self.config.max_files]
        unstaged = unstaged[: self.config.max_files]
        untracked = untracked[: self.config.max_files]

        summary = self._generate_summary(
            branch, staged, unstaged, untracked, ahead, behind
        )

        return GitStatusResult(
            is_git_repo=True,
            branch=branch,
            ahead=ahead,
            behind=behind,
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
            stash_count=stash_count,
            has_conflicts=has_conflicts,
            summary=summary,
        )

    async def _run_git(self, workdir: Path, *args: str) -> tuple[str, int]:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace").strip(), proc.returncode or 0

    async def _is_git_repo(self, workdir: Path) -> bool:
        _, code = await self._run_git(workdir, "rev-parse", "--git-dir")
        return code == 0

    async def _get_branch_info(self, workdir: Path) -> tuple[str | None, int, int]:
        branch_out, _ = await self._run_git(workdir, "branch", "--show-current")
        branch = branch_out or None

        ahead, behind = 0, 0
        if branch:
            status_out, _ = await self._run_git(
                workdir,
                "rev-list",
                "--left-right",
                "--count",
                f"{branch}@{{upstream}}...HEAD",
            )
            if status_out and "\t" in status_out:
                parts = status_out.split("\t")
                behind = int(parts[0]) if parts[0].isdigit() else 0
                ahead = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0

        return branch, ahead, behind

    async def _get_staged_files(self, workdir: Path) -> list[GitFileStatus]:
        out, _ = await self._run_git(workdir, "diff", "--cached", "--name-status")
        return self._parse_status_output(out, staged=True)

    async def _get_unstaged_files(self, workdir: Path) -> list[GitFileStatus]:
        out, _ = await self._run_git(workdir, "diff", "--name-status")
        return self._parse_status_output(out, staged=False)

    async def _get_untracked_files(self, workdir: Path) -> list[str]:
        out, _ = await self._run_git(
            workdir, "ls-files", "--others", "--exclude-standard"
        )
        return [f for f in out.splitlines() if f]

    async def _get_stash_count(self, workdir: Path) -> int:
        out, _ = await self._run_git(workdir, "stash", "list")
        return len(out.splitlines()) if out else 0

    async def _has_conflicts(self, workdir: Path) -> bool:
        out, _ = await self._run_git(workdir, "diff", "--name-only", "--diff-filter=U")
        return bool(out.strip())

    def _parse_status_output(self, output: str, staged: bool) -> list[GitFileStatus]:
        status_map = {
            "M": "modified",
            "A": "added",
            "D": "deleted",
            "R": "renamed",
            "C": "copied",
            "U": "conflict",
        }
        files = []
        for line in output.splitlines():
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) >= MIN_SPLIT_PARTS:
                status_char = parts[0][0] if parts[0] else "M"
                files.append(
                    GitFileStatus(
                        path=parts[1],
                        status=status_map.get(status_char, "unknown"),
                        staged=staged,
                    )
                )
        return files

    def _generate_summary(
        self,
        branch: str | None,
        staged: list[GitFileStatus],
        unstaged: list[GitFileStatus],
        untracked: list[str],
        ahead: int,
        behind: int,
    ) -> str:
        parts = []
        if branch:
            parts.append(f"On branch {branch}")
            if ahead or behind:
                sync = []
                if ahead:
                    sync.append(f"↑{ahead}")
                if behind:
                    sync.append(f"↓{behind}")
                parts.append(f"[{' '.join(sync)}]")

        counts = []
        if staged:
            counts.append(f"{len(staged)} staged")
        if unstaged:
            counts.append(f"{len(unstaged)} modified")
        if untracked:
            counts.append(f"{len(untracked)} untracked")

        if counts:
            parts.append(f"({', '.join(counts)})")
        elif not staged and not unstaged and not untracked:
            parts.append("(clean)")

        return " ".join(parts)

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        return ToolCallDisplay(summary="git_status")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, GitStatusResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        if not result.is_git_repo:
            return ToolResultDisplay(success=True, message="Not a git repository")

        lines = [f"🌿 {result.summary}"]

        if result.staged:
            lines.append("\n📦 Staged:")
            for f in result.staged[:MAX_STATUS_DISPLAY]:
                icon = {"added": "➕", "deleted": "➖", "modified": "✏️"}.get(
                    f.status, "•"
                )
                lines.append(f"  {icon} {f.path}")
            if len(result.staged) > MAX_STATUS_DISPLAY:
                lines.append(
                    f"  ... and {len(result.staged) - MAX_STATUS_DISPLAY} more"
                )

        if result.unstaged:
            lines.append("\n📝 Unstaged:")
            for f in result.unstaged[:MAX_STATUS_DISPLAY]:
                icon = {"added": "➕", "deleted": "➖", "modified": "✏️"}.get(
                    f.status, "•"
                )
                lines.append(f"  {icon} {f.path}")
            if len(result.unstaged) > MAX_STATUS_DISPLAY:
                lines.append(
                    f"  ... and {len(result.unstaged) - MAX_STATUS_DISPLAY} more"
                )

        if result.untracked:
            lines.append("\n❓ Untracked:")
            for f in result.untracked[:MAX_UNTRACKED_DISPLAY]:
                lines.append(f"  • {f}")
            if len(result.untracked) > MAX_UNTRACKED_DISPLAY:
                lines.append(
                    f"  ... and {len(result.untracked) - MAX_UNTRACKED_DISPLAY} more"
                )

        return ToolResultDisplay(
            success=True, message=result.summary, details={"output": "\n".join(lines)}
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Checking git status"
