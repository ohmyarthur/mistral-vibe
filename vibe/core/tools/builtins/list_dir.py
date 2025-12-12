from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, final

try:
    import aerofs

    HAS_AEROFS = True
except ImportError:
    HAS_AEROFS = False

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


class DirEntry(BaseModel):
    name: str
    is_dir: bool
    size: int | None = None
    children_count: int | None = None


class ListDirArgs(BaseModel):
    path: str = Field(
        default=".",
        description="Directory path to list. Defaults to current directory.",
    )
    max_depth: int = Field(
        default=1,
        description="Maximum depth to recurse (1 = no recursion, just immediate children).",
    )
    include_hidden: bool = Field(
        default=False, description="Include hidden files (starting with dot)."
    )


class ListDirResult(BaseModel):
    path: str
    entries: list[DirEntry]
    total_files: int
    total_dirs: int
    was_truncated: bool = False


class ListDirToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_entries: int = Field(
        default=200, description="Maximum number of entries to return."
    )


class ListDirState(BaseToolState):
    pass


class ListDir(
    BaseTool[ListDirArgs, ListDirResult, ListDirToolConfig, ListDirState],
    ToolUIData[ListDirArgs, ListDirResult],
):
    description: ClassVar[str] = (
        "List contents of a directory, showing files and subdirectories with their sizes. "
        "Use this instead of bash 'ls' for better structured output."
    )

    @final
    async def run(self, args: ListDirArgs) -> ListDirResult:
        dir_path = self._prepare_and_validate_path(args)
        entries, was_truncated = await self._list_directory(
            dir_path, args.max_depth, args.include_hidden
        )

        total_files = sum(1 for e in entries if not e.is_dir)
        total_dirs = sum(1 for e in entries if e.is_dir)

        return ListDirResult(
            path=str(dir_path),
            entries=entries,
            total_files=total_files,
            total_dirs=total_dirs,
            was_truncated=was_truncated,
        )

    def _prepare_and_validate_path(self, args: ListDirArgs) -> Path:
        path_str = args.path.strip() or "."
        dir_path = Path(path_str).expanduser()

        if not dir_path.is_absolute():
            dir_path = self.config.effective_workdir / dir_path

        dir_path = dir_path.resolve()

        if not dir_path.exists():
            raise ToolError(f"Directory not found: {dir_path}")
        if not dir_path.is_dir():
            raise ToolError(f"Path is not a directory: {dir_path}")

        return dir_path

    async def _list_directory(
        self, dir_path: Path, max_depth: int, include_hidden: bool
    ) -> tuple[list[DirEntry], bool]:
        entries: list[DirEntry] = []
        was_truncated = False

        try:
            if HAS_AEROFS:
                items = await aerofs.os.listdir(str(dir_path))  # type: ignore
            else:
                import asyncio

                items = await asyncio.to_thread(os.listdir, dir_path)

            items.sort(key=lambda x: (not Path(dir_path / x).is_dir(), x.lower()))

            for item in items:
                if len(entries) >= self.config.max_entries:
                    was_truncated = True
                    break

                if not include_hidden and item.startswith("."):
                    continue

                item_path = dir_path / item
                is_dir = item_path.is_dir()

                entry = DirEntry(
                    name=item,
                    is_dir=is_dir,
                    size=item_path.stat().st_size if not is_dir else None,
                    children_count=len(list(item_path.iterdir())) if is_dir else None,
                )
                entries.append(entry)

        except PermissionError:
            raise ToolError(f"Permission denied: {dir_path}")
        except OSError as e:
            raise ToolError(f"Error listing directory {dir_path}: {e}")

        return entries, was_truncated

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, ListDirArgs):
            return ToolCallDisplay(summary="list_dir")

        return ToolCallDisplay(
            summary=f"list_dir: {event.args.path}",
            details={
                "path": event.args.path,
                "max_depth": event.args.max_depth,
                "include_hidden": event.args.include_hidden,
            },
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ListDirResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        message = f"{result.total_files} files, {result.total_dirs} dirs"
        if result.was_truncated:
            message += " (truncated)"

        formatted_entries = []
        for entry in result.entries:
            if entry.is_dir:
                formatted_entries.append(
                    f"📁 {entry.name}/ ({entry.children_count} items)"
                )
            else:
                size_str = cls._format_size(entry.size or 0)
                formatted_entries.append(f"📄 {entry.name} ({size_str})")

        return ToolResultDisplay(
            success=True,
            message=message,
            details={
                "path": result.path,
                "entries": "\n".join(formatted_entries),
                "total_files": result.total_files,
                "total_dirs": result.total_dirs,
            },
        )

    @staticmethod
    def _format_size(size: int) -> str:
        size_f = float(size)
        kb = 1024
        for unit in ["B", "KB", "MB", "GB"]:
            if size_f < kb:
                return f"{int(size_f)}{unit}" if unit == "B" else f"{size_f:.1f}{unit}"
            size_f /= kb
        return f"{size_f:.1f}TB"

    @classmethod
    def get_status_text(cls) -> str:
        return "Listing directory"
