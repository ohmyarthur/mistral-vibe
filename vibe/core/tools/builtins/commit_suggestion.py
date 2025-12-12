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


class FileDiff(BaseModel):
    path: str
    status: str  # "added", "modified", "deleted", "renamed"
    additions: int = 0
    deletions: int = 0
    diff_preview: str = ""


class CommitSuggestionArgs(BaseModel):
    include_body: bool = Field(
        default=True,
        description="Include detailed commit body with bullet points.",
    )
    style: str = Field(
        default="conventional",
        description="Commit style: 'conventional' (feat/fix/etc), 'simple', or 'detailed'.",
    )
    max_files: int = Field(
        default=20,
        description="Maximum files to analyze.",
    )


class CommitSuggestionResult(BaseModel):
    has_changes: bool = False
    title: str = ""
    body: str = ""
    full_message: str = ""
    files: list[FileDiff] = Field(default_factory=list)
    stats: str = ""
    suggested_type: str = ""  # feat, fix, docs, refactor, test, chore


class CommitSuggestionToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class CommitSuggestionState(BaseToolState):
    pass


class CommitSuggestion(
    BaseTool[
        CommitSuggestionArgs,
        CommitSuggestionResult,
        CommitSuggestionToolConfig,
        CommitSuggestionState,
    ],
    ToolUIData[CommitSuggestionArgs, CommitSuggestionResult],
):
    description: ClassVar[str] = (
        "Analyze staged changes and suggest a commit message. "
        "Returns structured diff info and generates conventional commit message."
    )

    @final
    async def run(self, args: CommitSuggestionArgs) -> CommitSuggestionResult:
        workdir = self.config.effective_workdir

        is_git = await self._is_git_repo(workdir)
        if not is_git:
            raise ToolError("Not a git repository")

        files = await self._get_staged_files(workdir, args.max_files)

        if not files:
            unstaged = await self._get_unstaged_files(workdir)
            if unstaged:
                return CommitSuggestionResult(
                    has_changes=False,
                    title="No staged changes",
                    body=f"Found {len(unstaged)} unstaged files. Use 'git add' first.",
                    stats=f"{len(unstaged)} unstaged files",
                )
            return CommitSuggestionResult(
                has_changes=False,
                title="No changes to commit",
                body="Working tree clean.",
            )

        suggested_type = self._detect_commit_type(files)
        title = self._generate_title(files, suggested_type, args.style)
        body = self._generate_body(files) if args.include_body else ""

        full_message = title
        if body:
            full_message = f"{title}\n\n{body}"

        stats = await self._get_stats(workdir)

        return CommitSuggestionResult(
            has_changes=True,
            title=title,
            body=body,
            full_message=full_message,
            files=files,
            stats=stats,
            suggested_type=suggested_type,
        )

    async def _run_git(self, workdir: Path, *args: str) -> tuple[str, int]:
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            cwd=workdir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode("utf-8", errors="replace").strip(), proc.returncode or 0

    async def _is_git_repo(self, workdir: Path) -> bool:
        _, code = await self._run_git(workdir, "rev-parse", "--git-dir")
        return code == 0

    async def _get_staged_files(self, workdir: Path, max_files: int) -> list[FileDiff]:
        out, _ = await self._run_git(workdir, "diff", "--cached", "--name-status")
        files: list[FileDiff] = []

        status_map = {
            "A": "added", "M": "modified", "D": "deleted", "R": "renamed"
        }

        for line in out.splitlines()[:max_files]:
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) >= 2:
                status_char = parts[0][0]
                path = parts[1]

                numstat, _ = await self._run_git(
                    workdir, "diff", "--cached", "--numstat", "--", path
                )
                additions = deletions = 0
                if numstat:
                    nums = numstat.split()
                    if len(nums) >= 2:
                        additions = int(nums[0]) if nums[0].isdigit() else 0
                        deletions = int(nums[1]) if nums[1].isdigit() else 0

                diff_preview, _ = await self._run_git(
                    workdir, "diff", "--cached", "--", path
                )
                diff_preview = diff_preview[:500] if diff_preview else ""

                files.append(FileDiff(
                    path=path,
                    status=status_map.get(status_char, "modified"),
                    additions=additions,
                    deletions=deletions,
                    diff_preview=diff_preview,
                ))

        return files

    async def _get_unstaged_files(self, workdir: Path) -> list[str]:
        out, _ = await self._run_git(workdir, "diff", "--name-only")
        return [f for f in out.splitlines() if f]

    async def _get_stats(self, workdir: Path) -> str:
        out, _ = await self._run_git(workdir, "diff", "--cached", "--stat")
        lines = out.splitlines()
        if lines:
            return lines[-1].strip()
        return ""

    def _detect_commit_type(self, files: list[FileDiff]) -> str:
        paths = [f.path.lower() for f in files]
        statuses = [f.status for f in files]

        if any("test" in p for p in paths):
            return "test"
        if any(p.endswith(".md") for p in paths):
            return "docs"
        if any(p.startswith("config") or "config" in p for p in paths):
            return "chore"
        if all(s == "added" for s in statuses):
            return "feat"
        if any("fix" in p for p in paths):
            return "fix"

        total_changes = sum(f.additions + f.deletions for f in files)
        if total_changes < 20:
            return "fix"

        return "feat"

    def _generate_title(
        self, files: list[FileDiff], commit_type: str, style: str
    ) -> str:
        if len(files) == 1:
            file = files[0]
            name = Path(file.path).stem
            action = {
                "added": "add",
                "modified": "update",
                "deleted": "remove",
                "renamed": "rename",
            }.get(file.status, "update")

            if style == "conventional":
                return f"{commit_type}: {action} {name}"
            elif style == "simple":
                return f"{action.capitalize()} {name}"
            else:
                return f"{action.capitalize()} {file.path}"

        dirs = set()
        for f in files:
            parts = Path(f.path).parts
            if len(parts) > 1:
                dirs.add(parts[0])

        if len(dirs) == 1:
            scope = list(dirs)[0]
            if style == "conventional":
                return f"{commit_type}({scope}): update {len(files)} files"
            return f"Update {scope} ({len(files)} files)"

        if style == "conventional":
            return f"{commit_type}: update {len(files)} files"
        return f"Update {len(files)} files"

    def _generate_body(self, files: list[FileDiff]) -> str:
        lines = []

        added = [f for f in files if f.status == "added"]
        modified = [f for f in files if f.status == "modified"]
        deleted = [f for f in files if f.status == "deleted"]

        if added:
            lines.append("Added:")
            for f in added[:5]:
                lines.append(f"  - {f.path}")
            if len(added) > 5:
                lines.append(f"  - ... and {len(added) - 5} more")

        if modified:
            lines.append("\nModified:")
            for f in modified[:5]:
                lines.append(f"  - {f.path} (+{f.additions}/-{f.deletions})")
            if len(modified) > 5:
                lines.append(f"  - ... and {len(modified) - 5} more")

        if deleted:
            lines.append("\nDeleted:")
            for f in deleted[:5]:
                lines.append(f"  - {f.path}")

        return "\n".join(lines)

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        return ToolCallDisplay(summary="Analyzing changes for commit message")

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, CommitSuggestionResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        if not result.has_changes:
            return ToolResultDisplay(success=True, message=result.title)

        lines = [
            "📝 Suggested commit message:",
            "",
            f"  {result.title}",
        ]

        if result.body:
            lines.append("")
            for line in result.body.split("\n")[:10]:
                lines.append(f"  {line}")

        if result.stats:
            lines.extend(["", f"📊 {result.stats}"])

        return ToolResultDisplay(
            success=True,
            message=f"Suggested: {result.title}",
            details={"output": "\n".join(lines)},
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Analyzing changes"
