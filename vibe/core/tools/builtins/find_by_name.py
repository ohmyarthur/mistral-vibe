from __future__ import annotations

import fnmatch
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


class FileMatch(BaseModel):
    path: str
    name: str
    is_dir: bool
    size: int | None = None


class FindByNameArgs(BaseModel):
    pattern: str = Field(
        description="Glob pattern to match (e.g., '*.py', 'test_*.py', '*config*')."
    )
    path: str = Field(
        default=".",
        description="Directory to search in. Defaults to current directory.",
    )
    max_depth: int = Field(default=10, description="Maximum depth to recurse.")
    file_type: str = Field(
        default="any", description="Filter by type: 'file', 'directory', or 'any'."
    )
    include_hidden: bool = Field(
        default=False, description="Include hidden files/directories."
    )


class FindByNameResult(BaseModel):
    pattern: str
    search_path: str
    matches: list[FileMatch]
    total_matches: int
    was_truncated: bool = False


class FindByNameToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_results: int = Field(
        default=100, description="Maximum number of matches to return."
    )
    default_excludes: list[str] = Field(
        default_factory=lambda: [
            ".git",
            "__pycache__",
            "node_modules",
            ".venv",
            "venv",
            ".pytest_cache",
            "*.pyc",
            ".DS_Store",
        ],
        description="Patterns to exclude from search.",
    )


class FindByNameState(BaseToolState):
    pass


MAX_MATCHES_DISPLAY = 20


class FindByName(
    BaseTool[FindByNameArgs, FindByNameResult, FindByNameToolConfig, FindByNameState],
    ToolUIData[FindByNameArgs, FindByNameResult],
):
    description: ClassVar[str] = (
        "Search for files and directories by name pattern using glob matching. "
        "Faster alternative to bash 'find' with structured output."
    )

    @final
    async def run(self, args: FindByNameArgs) -> FindByNameResult:
        search_path = self._prepare_and_validate_path(args)
        matches, was_truncated = await self._find_files(
            search_path,
            args.pattern,
            args.max_depth,
            args.file_type,
            args.include_hidden,
        )

        return FindByNameResult(
            pattern=args.pattern,
            search_path=str(search_path),
            matches=matches,
            total_matches=len(matches),
            was_truncated=was_truncated,
        )

    def _prepare_and_validate_path(self, args: FindByNameArgs) -> Path:
        path_str = args.path.strip() or "."
        search_path = Path(path_str).expanduser()

        if not search_path.is_absolute():
            search_path = self.config.effective_workdir / search_path

        search_path = search_path.resolve()

        if not search_path.exists():
            raise ToolError(f"Search path not found: {search_path}")
        if not search_path.is_dir():
            raise ToolError(f"Search path is not a directory: {search_path}")

        return search_path

    def _should_exclude(self, path: Path) -> bool:
        name = path.name
        for pattern in self.config.default_excludes:
            if fnmatch.fnmatch(name, pattern):
                return True
        return False

    async def _find_files(
        self,
        search_path: Path,
        pattern: str,
        max_depth: int,
        file_type: str,
        include_hidden: bool,
    ) -> tuple[list[FileMatch], bool]:
        import asyncio

        return await asyncio.to_thread(
            self._find_files_sync,
            search_path,
            pattern,
            max_depth,
            file_type,
            include_hidden,
        )

    def _find_files_sync(
        self,
        search_path: Path,
        pattern: str,
        max_depth: int,
        file_type: str,
        include_hidden: bool,
    ) -> tuple[list[FileMatch], bool]:
        matches: list[FileMatch] = []
        was_truncated = False

        def search_recursive(current_path: Path, depth: int) -> bool:
            nonlocal was_truncated

            if depth > max_depth:
                return True
            if len(matches) >= self.config.max_results:
                was_truncated = True
                return False

            try:
                for item in sorted(
                    current_path.iterdir(), key=lambda x: x.name.lower()
                ):
                    if len(matches) >= self.config.max_results:
                        was_truncated = True
                        return False

                    if self._should_exclude(item):
                        continue

                    if not include_hidden and item.name.startswith("."):
                        continue

                    is_dir = item.is_dir()

                    type_match = (
                        file_type == "any"
                        or (file_type == "file" and not is_dir)
                        or (file_type == "directory" and is_dir)
                    )

                    if fnmatch.fnmatch(item.name, pattern) and type_match:
                        try:
                            size = item.stat().st_size if not is_dir else None
                        except OSError:
                            size = None

                        rel_path = str(item.relative_to(self.config.effective_workdir))
                        matches.append(
                            FileMatch(
                                path=rel_path, name=item.name, is_dir=is_dir, size=size
                            )
                        )

                    if is_dir:
                        if not search_recursive(item, depth + 1):
                            return False

            except PermissionError:
                pass
            except OSError:
                pass

            return True

        search_recursive(search_path, 0)
        return matches, was_truncated

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, FindByNameArgs):
            return ToolCallDisplay(summary="find_by_name")

        return ToolCallDisplay(
            summary=f"find_by_name: '{event.args.pattern}' in {event.args.path}",
            details={
                "pattern": event.args.pattern,
                "path": event.args.path,
                "max_depth": event.args.max_depth,
                "file_type": event.args.file_type,
            },
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, FindByNameResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        message = f"Found {result.total_matches} matches for '{result.pattern}'"
        if result.was_truncated:
            message += " (truncated)"

        formatted_matches = []
        for match in result.matches[:MAX_MATCHES_DISPLAY]:
            icon = "📁" if match.is_dir else "📄"
            formatted_matches.append(f"{icon} {match.path}")

        if len(result.matches) > MAX_MATCHES_DISPLAY:
            formatted_matches.append(
                f"... and {len(result.matches) - MAX_MATCHES_DISPLAY} more"
            )

        return ToolResultDisplay(
            success=True,
            message=message,
            details={
                "pattern": result.pattern,
                "search_path": result.search_path,
                "matches": "\n".join(formatted_matches),
                "total_matches": result.total_matches,
            },
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Searching files"
