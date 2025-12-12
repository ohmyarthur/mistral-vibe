from __future__ import annotations

import asyncio
import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, final

try:
    from rapidfuzz import fuzz
    HAS_RAPIDFUZZ = True
except ImportError:
    HAS_RAPIDFUZZ = False

try:
    import aerofs as aiofiles
except ImportError:
    import aiofiles  # type: ignore[no-redef]

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

class MatchTier(str, Enum):
    EXACT = "exact"
    NORMALIZED = "normalized"
    ANCHORED = "anchored"
    LINE_RANGE = "line_range"
    FUZZY = "fuzzy"
    FAILED = "failed"


class EditBlock(BaseModel):
    search: str = Field(description="Text to find in the file.")
    replace: str = Field(description="Replacement text.")

    context_before: str | None = Field(
        default=None,
        description="Lines before the search text for anchoring.",
    )
    context_after: str | None = Field(
        default=None,
        description="Lines after the search text for anchoring.",
    )
    line_start: int | None = Field(
        default=None,
        description="Start of search range (1-indexed).",
    )
    line_end: int | None = Field(
        default=None,
        description="End of search range (1-indexed).",
    )


class FileEdit(BaseModel):
    path: str = Field(description="Path to the file to edit.")
    edits: list[EditBlock] = Field(description="Edits to apply in order.")
    expected_hash: str | None = Field(
        default=None,
        description="MD5 hash of file content when edit was planned.",
    )


class MatchResult(BaseModel):
    success: bool
    tier: MatchTier
    confidence: float
    match_start: int | None = None
    match_end: int | None = None
    warning: str | None = None
    suggestion: str | None = None


class EditBlockResult(BaseModel):
    edit_index: int
    success: bool
    match_result: MatchResult
    original_text: str | None = None
    applied_text: str | None = None


class FileEditResult(BaseModel):
    path: str
    success: bool
    edits_applied: int = 0
    edits_failed: int = 0
    block_results: list[EditBlockResult] = Field(default_factory=list)
    diff_preview: str = ""
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reject_content: str | None = None


class MultiEditArgs(BaseModel):
    files: list[FileEdit] = Field(description="Files and their edits.")

    dry_run: bool = Field(
        default=True,
        description="Preview only, don't apply changes.",
    )
    check_only: bool = Field(
        default=False,
        description="Validate matches without generating diff.",
    )
    create_backup: bool = Field(
        default=True,
        description="Create .bak files before modifying.",
    )
    fail_fast: bool = Field(
        default=True,
        description="Stop on first error (recommended for safety).",
    )
    min_confidence: float = Field(
        default=0.85,
        description="Minimum confidence threshold for applying edits.",
    )


class MultiEditResult(BaseModel):
    success: bool
    state: Literal["checked", "previewed", "applied", "failed", "rolled_back"]

    files_checked: int = 0
    files_modified: int = 0
    total_edits: int = 0
    edits_applied: int = 0
    edits_failed: int = 0

    results: list[FileEditResult] = Field(default_factory=list)

    backup_paths: dict[str, str] | None = None
    reject_files: dict[str, str] | None = None

    transaction_id: str | None = None
    can_apply: bool = False
    summary: str = ""


@dataclass
class MatchContext:
    content: str
    lines: list[str]
    min_confidence: float


class MatchingEngine:
    @classmethod
    def match(
        cls,
        content: str,
        edit: EditBlock,
        min_confidence: float = 0.85,
    ) -> MatchResult:
        ctx = MatchContext(
            content=content,
            lines=content.splitlines(keepends=True),
            min_confidence=min_confidence,
        )

        result = cls._tier1_exact(ctx, edit)
        if result.success:
            return result

        result = cls._tier2_normalized(ctx, edit)
        if result.success:
            return result

        if edit.context_before or edit.context_after:
            result = cls._tier3_anchored(ctx, edit)
            if result.success:
                return result

        if edit.line_start is not None:
            result = cls._tier4_line_range(ctx, edit)
            if result.success:
                return result

        result = cls._tier5_fuzzy(ctx, edit)
        return result

    @classmethod
    def _tier1_exact(cls, ctx: MatchContext, edit: EditBlock) -> MatchResult:
        idx = ctx.content.find(edit.search)
        if idx != -1:
            return MatchResult(
                success=True,
                tier=MatchTier.EXACT,
                confidence=1.0,
                match_start=idx,
                match_end=idx + len(edit.search),
            )
        return MatchResult(success=False, tier=MatchTier.EXACT, confidence=0.0)

    @classmethod
    def _tier2_normalized(cls, ctx: MatchContext, edit: EditBlock) -> MatchResult:
        search_lines = edit.search.splitlines()
        search_stripped = [line.strip() for line in search_lines]

        for i, line in enumerate(ctx.lines):
            if line.strip() == search_stripped[0]:
                match_found = True
                for j, expected in enumerate(search_stripped):
                    if i + j >= len(ctx.lines):
                        match_found = False
                        break
                    if ctx.lines[i + j].strip() != expected:
                        match_found = False
                        break

                if match_found:
                    start = sum(len(l) for l in ctx.lines[:i])
                    end = sum(len(l) for l in ctx.lines[:i + len(search_lines)])

                    return MatchResult(
                        success=True,
                        tier=MatchTier.NORMALIZED,
                        confidence=0.95,
                        match_start=start,
                        match_end=end,
                        warning="Matched via whitespace normalization",
                    )

        return MatchResult(success=False, tier=MatchTier.NORMALIZED, confidence=0.0)

    @classmethod
    def _tier3_anchored(cls, ctx: MatchContext, edit: EditBlock) -> MatchResult:
        pattern_parts = []
        if edit.context_before:
            pattern_parts.append(re.escape(edit.context_before.strip()))
        pattern_parts.append(re.escape(edit.search))
        if edit.context_after:
            pattern_parts.append(re.escape(edit.context_after.strip()))

        pattern = r'\s*'.join(pattern_parts)

        match = re.search(pattern, ctx.content, re.MULTILINE | re.DOTALL)
        if match:
            search_start = ctx.content.find(edit.search, match.start())
            if search_start != -1 and search_start <= match.end():
                return MatchResult(
                    success=True,
                    tier=MatchTier.ANCHORED,
                    confidence=0.90,
                    match_start=search_start,
                    match_end=search_start + len(edit.search),
                    warning="Matched via context anchoring",
                )

        return MatchResult(success=False, tier=MatchTier.ANCHORED, confidence=0.0)

    @classmethod
    def _tier4_line_range(cls, ctx: MatchContext, edit: EditBlock) -> MatchResult:
        start_line = (edit.line_start or 1) - 1  # Convert to 0-indexed
        end_line = edit.line_end or len(ctx.lines)

        if start_line < 0 or end_line > len(ctx.lines):
            return MatchResult(
                success=False,
                tier=MatchTier.LINE_RANGE,
                confidence=0.0,
                warning=f"Line range {start_line+1}-{end_line} out of bounds",
            )

        range_lines = ctx.lines[start_line:end_line]
        range_content = ''.join(range_lines)

        idx = range_content.find(edit.search)
        if idx != -1:
            offset = sum(len(l) for l in ctx.lines[:start_line])
            return MatchResult(
                success=True,
                tier=MatchTier.LINE_RANGE,
                confidence=0.85,
                match_start=offset + idx,
                match_end=offset + idx + len(edit.search),
                warning=f"Matched in line range {start_line+1}-{end_line}",
            )

        return MatchResult(success=False, tier=MatchTier.LINE_RANGE, confidence=0.0)

    @classmethod
    def _tier5_fuzzy(cls, ctx: MatchContext, edit: EditBlock) -> MatchResult:
        if not HAS_RAPIDFUZZ:
            return MatchResult(
                success=False,
                tier=MatchTier.FUZZY,
                confidence=0.0,
                warning="Fuzzy matching unavailable (rapidfuzz not installed)",
            )

        best_score = 0.0
        best_match = ""
        best_pos = -1

        search_len = len(edit.search)

        for i in range(len(ctx.content) - min(search_len, 10)):
            window = ctx.content[i:i + search_len + 50]
            score = fuzz.ratio(edit.search, window[:search_len]) / 100.0

            if score > best_score:
                best_score = score
                best_match = window[:search_len]
                best_pos = i

        if best_score >= 0.70:
            return MatchResult(
                success=False,  # Never auto-apply fuzzy
                tier=MatchTier.FUZZY,
                confidence=best_score,
                match_start=best_pos,
                match_end=best_pos + len(best_match),
                warning=f"Fuzzy match found ({best_score:.0%} confidence) - manual review required",
                suggestion=best_match,
            )

        return MatchResult(
            success=False,
            tier=MatchTier.FAILED,
            confidence=0.0,
            warning="No match found",
        )


class SafetyChecker:
    @classmethod
    async def check_all(cls, workdir: Path) -> tuple[bool, list[str]]:
        errors: list[str] = []

        merge_head = workdir / ".git" / "MERGE_HEAD"
        if merge_head.exists():
            errors.append("Git merge in progress. Resolve before editing.")

        rebase_dir = workdir / ".git" / "rebase-merge"
        rebase_apply = workdir / ".git" / "rebase-apply"
        if rebase_dir.exists() or rebase_apply.exists():
            errors.append("Git rebase in progress. Complete or abort first.")

        index_lock = workdir / ".git" / "index.lock"
        if index_lock.exists():
            errors.append("Git index is locked. Another git process may be running.")

        return len(errors) == 0, errors


class DiffGenerator:
    @classmethod
    def generate(
        cls,
        original: str,
        modified: str,
        path: str,
        context_lines: int = 3,
    ) -> str:
        import difflib

        orig_lines = original.splitlines(keepends=True)
        mod_lines = modified.splitlines(keepends=True)

        diff = difflib.unified_diff(
            orig_lines,
            mod_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=context_lines,
        )

        return ''.join(diff)


@dataclass
class EditTransaction:
    workdir: Path
    original_contents: dict[Path, str] = field(default_factory=dict)
    backup_paths: dict[Path, Path] = field(default_factory=dict)
    modified_contents: dict[Path, str] = field(default_factory=dict)

    async def read_file(self, path: Path) -> str:
        async with aiofiles.open(path, 'r', encoding='utf-8') as f:
            content = await f.read()
        self.original_contents[path] = content
        return content

    def compute_hash(self, content: str) -> str:
        return hashlib.md5(content.encode('utf-8')).hexdigest()

    async def create_backup(self, path: Path) -> Path:
        backup_path = path.with_suffix(path.suffix + '.bak')

        async with aiofiles.open(path, 'r', encoding='utf-8') as f:
            content = await f.read()

        async with aiofiles.open(backup_path, 'w', encoding='utf-8') as f:
            await f.write(content)

        self.backup_paths[path] = backup_path
        return backup_path

    async def apply(self, path: Path, content: str) -> None:
        async with aiofiles.open(path, 'w', encoding='utf-8') as f:
            await f.write(content)
        self.modified_contents[path] = content

    async def rollback(self, path: Path) -> bool:
        if path in self.original_contents:
            async with aiofiles.open(path, 'w', encoding='utf-8') as f:
                await f.write(self.original_contents[path])
            return True
        return False

    async def rollback_all(self) -> int:
        count = 0
        for path in self.modified_contents:
            if await self.rollback(path):
                count += 1
        return count


class MultiEditConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ASK
    max_file_size: int = Field(default=1_000_000, description="Max file size in bytes.")


class MultiEditState(BaseToolState):
    last_transaction_id: str | None = None


class MultiEdit(
    BaseTool[MultiEditArgs, MultiEditResult, MultiEditConfig, MultiEditState],
    ToolUIData[MultiEditArgs, MultiEditResult],
):
    description: ClassVar[str] = (
        "Perform atomic multi-file edits with precision matching. "
        "Supports dry-run preview, conflict detection, and automatic rollback. "
        "Use for surgical code changes across multiple files."
    )

    @final
    async def run(self, args: MultiEditArgs) -> MultiEditResult:
        import uuid

        workdir = self.config.effective_workdir
        transaction_id = str(uuid.uuid4())[:8]

        safe, errors = await SafetyChecker.check_all(workdir)
        if not safe:
            return MultiEditResult(
                success=False,
                state="failed",
                summary=f"Safety check failed: {'; '.join(errors)}",
            )

        transaction = EditTransaction(workdir=workdir)
        results: list[FileEditResult] = []
        total_edits = sum(len(f.edits) for f in args.files)
        edits_applied = 0
        edits_failed = 0
        backup_paths: dict[str, str] = {}
        reject_files: dict[str, str] = {}

        try:
            for file_edit in args.files:
                file_result = await self._process_file(
                    file_edit=file_edit,
                    transaction=transaction,
                    args=args,
                    workdir=workdir,
                )
                results.append(file_result)

                edits_applied += file_result.edits_applied
                edits_failed += file_result.edits_failed

                if file_result.reject_content:
                    reject_files[file_edit.path] = file_result.reject_content

                if not file_result.success and args.fail_fast:
                    await transaction.rollback_all()
                    return MultiEditResult(
                        success=False,
                        state="rolled_back",
                        files_checked=len(results),
                        files_modified=0,
                        total_edits=total_edits,
                        edits_applied=0,
                        edits_failed=edits_failed,
                        results=results,
                        reject_files=reject_files if reject_files else None,
                        transaction_id=transaction_id,
                        can_apply=False,
                        summary=f"Failed and rolled back: {file_result.errors[0] if file_result.errors else 'Unknown error'}",
                    )

            for orig, bak in transaction.backup_paths.items():
                backup_paths[str(orig)] = str(bak)

            all_success = all(r.success for r in results)

            if args.check_only:
                state = "checked"
            elif args.dry_run:
                state = "previewed"
            else:
                state = "applied" if all_success else "failed"

            return MultiEditResult(
                success=all_success,
                state=state,
                files_checked=len(results),
                files_modified=len([r for r in results if r.edits_applied > 0]),
                total_edits=total_edits,
                edits_applied=edits_applied,
                edits_failed=edits_failed,
                results=results,
                backup_paths=backup_paths if backup_paths else None,
                reject_files=reject_files if reject_files else None,
                transaction_id=transaction_id,
                can_apply=all_success and args.dry_run,
                summary=self._generate_summary(results, state, edits_applied, edits_failed),
            )

        except Exception as e:
            await transaction.rollback_all()
            return MultiEditResult(
                success=False,
                state="failed",
                results=results,
                transaction_id=transaction_id,
                summary=f"Error: {str(e)}",
            )

    async def _process_file(
        self,
        file_edit: FileEdit,
        transaction: EditTransaction,
        args: MultiEditArgs,
        workdir: Path,
    ) -> FileEditResult:
        path = Path(file_edit.path)
        if not path.is_absolute():
            path = workdir / path
        path = path.resolve()

        errors: list[str] = []
        warnings: list[str] = []
        block_results: list[EditBlockResult] = []

        if not path.exists():
            return FileEditResult(
                path=str(path),
                success=False,
                errors=[f"File not found: {path}"],
            )

        if path.stat().st_size > self.config.max_file_size:
            return FileEditResult(
                path=str(path),
                success=False,
                errors=[f"File too large: {path.stat().st_size} bytes"],
            )

        try:
            content = await transaction.read_file(path)
        except Exception as e:
            return FileEditResult(
                path=str(path),
                success=False,
                errors=[f"Failed to read file: {e}"],
            )

        if file_edit.expected_hash:
            current_hash = transaction.compute_hash(content)
            if current_hash != file_edit.expected_hash:
                return FileEditResult(
                    path=str(path),
                    success=False,
                    errors=["File has changed since edit was planned (hash mismatch)"],
                )

        modified_content = content
        edits_applied = 0
        reject_parts: list[str] = []

        for i, edit in enumerate(file_edit.edits):
            match_result = MatchingEngine.match(
                modified_content,
                edit,
                args.min_confidence,
            )

            block_result = EditBlockResult(
                edit_index=i,
                success=match_result.success,
                match_result=match_result,
            )

            if match_result.success and match_result.confidence >= args.min_confidence:
                start = match_result.match_start
                end = match_result.match_end

                if start is not None and end is not None:
                    block_result.original_text = modified_content[start:end]
                    modified_content = (
                        modified_content[:start] +
                        edit.replace +
                        modified_content[end:]
                    )
                    block_result.applied_text = edit.replace
                    edits_applied += 1

                    if match_result.warning:
                        warnings.append(f"Edit {i+1}: {match_result.warning}")
            else:
                errors.append(f"Edit {i+1}: {match_result.warning or 'No match found'}")
                reject_parts.append(self._format_reject(edit, match_result))

            block_results.append(block_result)

        diff_preview = ""
        if content != modified_content:
            diff_preview = DiffGenerator.generate(content, modified_content, str(path))
        if not args.dry_run and not args.check_only and edits_applied > 0:
            if args.create_backup:
                await transaction.create_backup(path)
            await transaction.apply(path, modified_content)

        success = len(errors) == 0

        return FileEditResult(
            path=str(path),
            success=success,
            edits_applied=edits_applied,
            edits_failed=len(file_edit.edits) - edits_applied,
            block_results=block_results,
            diff_preview=diff_preview,
            errors=errors,
            warnings=warnings,
            reject_content='\n'.join(reject_parts) if reject_parts else None,
        )

    def _format_reject(self, edit: EditBlock, match: MatchResult) -> str:
        lines = [
            f"# Rejected edit (confidence: {match.confidence:.0%})",
            f"# Tier: {match.tier.value}",
            f"# Warning: {match.warning or 'None'}",
            "",
            "<<<<<<< SEARCH",
            edit.search,
            "=======",
            edit.replace,
            ">>>>>>> REPLACE",
        ]
        if match.suggestion:
            lines.extend([
                "",
                "# Suggested match:",
                match.suggestion,
            ])
        return '\n'.join(lines)

    def _generate_summary(
        self,
        results: list[FileEditResult],
        state: str,
        edits_applied: int,
        edits_failed: int,
    ) -> str:
        if state == "checked":
            return f"✓ Checked {len(results)} file(s): {edits_applied} edits valid"
        elif state == "previewed":
            return f"👁 Preview: {edits_applied} edit(s) ready to apply"
        elif state == "applied":
            return f"✅ Applied {edits_applied} edit(s) to {len(results)} file(s)"
        elif state == "rolled_back":
            return f"⏪ Rolled back: {edits_failed} edit(s) failed"
        else:
            return f"❌ Failed: {edits_failed} edit(s) could not be applied"

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, MultiEditArgs):
            return ToolCallDisplay(summary="multi_edit")

        files = len(event.args.files)
        edits = sum(len(f.edits) for f in event.args.files)
        mode = "check" if event.args.check_only else ("preview" if event.args.dry_run else "apply")

        return ToolCallDisplay(
            summary=f"multi_edit: {files} file(s), {edits} edit(s) [{mode}]",
            details={
                "files": files,
                "edits": edits,
                "mode": mode,
            },
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, MultiEditResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        lines = [result.summary]

        if result.results:
            lines.append("")
            for fr in result.results:
                icon = "✅" if fr.success else "❌"
                lines.append(f"{icon} {Path(fr.path).name}: {fr.edits_applied}/{len(fr.block_results)} edits")

                if fr.diff_preview and len(fr.diff_preview) < 1000:
                    lines.append("```diff")
                    lines.append(fr.diff_preview[:800])
                    lines.append("```")

        return ToolResultDisplay(
            success=result.success,
            message=result.summary,
            details={"output": "\n".join(lines)},
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Editing files"
