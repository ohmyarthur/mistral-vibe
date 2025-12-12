from __future__ import annotations

import ast
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


class CodeSymbol(BaseModel):
    name: str
    type: str  # "class", "function", "method", "variable"
    line_start: int
    line_end: int
    signature: str | None = None
    docstring: str | None = None
    children: list[CodeSymbol] = Field(default_factory=list)


class ViewFileOutlineArgs(BaseModel):
    path: str = Field(description="Path to the file to analyze.")
    include_docstrings: bool = Field(
        default=True,
        description="Include docstrings in output.",
    )
    max_depth: int = Field(
        default=2,
        description="Maximum nesting depth (1=top-level only, 2=include methods).",
    )


class ViewFileOutlineResult(BaseModel):
    path: str
    language: str
    total_lines: int
    symbols: list[CodeSymbol]
    summary: str


class ViewFileOutlineToolConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_file_size: int = Field(default=500_000, description="Max file size in bytes.")


class ViewFileOutlineState(BaseToolState):
    pass


class ViewFileOutline(
    BaseTool[
        ViewFileOutlineArgs,
        ViewFileOutlineResult,
        ViewFileOutlineToolConfig,
        ViewFileOutlineState,
    ],
    ToolUIData[ViewFileOutlineArgs, ViewFileOutlineResult],
):
    description: ClassVar[str] = (
        "Parse a source file and return its structure: classes, functions, methods with line numbers. "
        "Use this to understand code structure before making edits."
    )

    SUPPORTED_EXTENSIONS = {".py": "python", ".pyi": "python"}

    @final
    async def run(self, args: ViewFileOutlineArgs) -> ViewFileOutlineResult:
        file_path = self._prepare_and_validate_path(args)
        language = self._detect_language(file_path)

        content = file_path.read_text(encoding="utf-8", errors="ignore")
        total_lines = len(content.splitlines())

        if language == "python":
            symbols = self._parse_python(content, args.include_docstrings, args.max_depth)
        else:
            symbols = []

        summary = self._generate_summary(symbols)

        return ViewFileOutlineResult(
            path=str(file_path),
            language=language,
            total_lines=total_lines,
            symbols=symbols,
            summary=summary,
        )

    def _prepare_and_validate_path(self, args: ViewFileOutlineArgs) -> Path:
        path_str = args.path.strip()
        if not path_str:
            raise ToolError("Path cannot be empty")

        file_path = Path(path_str).expanduser()
        if not file_path.is_absolute():
            file_path = self.config.effective_workdir / file_path

        file_path = file_path.resolve()

        if not file_path.exists():
            raise ToolError(f"File not found: {file_path}")
        if file_path.is_dir():
            raise ToolError(f"Path is a directory: {file_path}")
        if file_path.stat().st_size > self.config.max_file_size:
            raise ToolError(f"File too large: {file_path.stat().st_size} bytes")

        return file_path

    def _detect_language(self, file_path: Path) -> str:
        ext = file_path.suffix.lower()
        return self.SUPPORTED_EXTENSIONS.get(ext, "unknown")

    def _parse_python(
        self, content: str, include_docstrings: bool, max_depth: int
    ) -> list[CodeSymbol]:
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            raise ToolError(f"Python syntax error: {e}")

        symbols: list[CodeSymbol] = []

        for node in ast.iter_child_nodes(tree):
            symbol = self._node_to_symbol(node, include_docstrings, max_depth, depth=1)
            if symbol:
                symbols.append(symbol)

        return symbols

    def _node_to_symbol(
        self,
        node: ast.AST,
        include_docstrings: bool,
        max_depth: int,
        depth: int,
    ) -> CodeSymbol | None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            signature = self._get_function_signature(node)
            docstring = ast.get_docstring(node) if include_docstrings else None

            return CodeSymbol(
                name=node.name,
                type="function",
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                signature=signature,
                docstring=docstring[:200] + "..." if docstring and len(docstring) > 200 else docstring,
            )

        elif isinstance(node, ast.ClassDef):
            docstring = ast.get_docstring(node) if include_docstrings else None
            children: list[CodeSymbol] = []

            if depth < max_depth:
                for child in ast.iter_child_nodes(node):
                    child_symbol = self._node_to_symbol(
                        child, include_docstrings, max_depth, depth + 1
                    )
                    if child_symbol:
                        child_symbol.type = "method" if child_symbol.type == "function" else child_symbol.type
                        children.append(child_symbol)

            bases = [self._get_name(base) for base in node.bases]
            signature = f"class {node.name}({', '.join(bases)})" if bases else f"class {node.name}"

            return CodeSymbol(
                name=node.name,
                type="class",
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
                signature=signature,
                docstring=docstring[:200] + "..." if docstring and len(docstring) > 200 else docstring,
                children=children,
            )

        return None

    def _get_function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        args = []
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {self._get_name(arg.annotation)}"
            args.append(arg_str)

        returns = ""
        if node.returns:
            returns = f" -> {self._get_name(node.returns)}"

        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        return f"{prefix} {node.name}({', '.join(args)}){returns}"

    def _get_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Subscript):
            return f"{self._get_name(node.value)}[{self._get_name(node.slice)}]"
        elif isinstance(node, ast.Constant):
            return repr(node.value)
        elif isinstance(node, ast.Tuple):
            return f"({', '.join(self._get_name(e) for e in node.elts)})"
        elif isinstance(node, ast.BinOp):
            return f"{self._get_name(node.left)} | {self._get_name(node.right)}"
        return "..."

    def _generate_summary(self, symbols: list[CodeSymbol]) -> str:
        classes = sum(1 for s in symbols if s.type == "class")
        functions = sum(1 for s in symbols if s.type == "function")
        methods = sum(
            len([c for c in s.children if c.type == "method"])
            for s in symbols if s.type == "class"
        )
        return f"{classes} classes, {functions} functions, {methods} methods"

    @classmethod
    def get_call_display(cls, event: ToolCallEvent) -> ToolCallDisplay:
        if not isinstance(event.args, ViewFileOutlineArgs):
            return ToolCallDisplay(summary="view_file_outline")

        return ToolCallDisplay(
            summary=f"view_file_outline: {event.args.path}",
            details={"path": event.args.path},
        )

    @classmethod
    def get_result_display(cls, event: ToolResultEvent) -> ToolResultDisplay:
        if not isinstance(event.result, ViewFileOutlineResult):
            return ToolResultDisplay(
                success=False, message=event.error or event.skip_reason or "No result"
            )

        result = event.result
        lines = [f"📄 {Path(result.path).name} ({result.language}, {result.total_lines} lines)"]
        lines.append(f"   {result.summary}")
        lines.append("")

        for symbol in result.symbols:
            icon = "🔷" if symbol.type == "class" else "🔹"
            lines.append(f"{icon} {symbol.signature} (L{symbol.line_start}-{symbol.line_end})")
            for child in symbol.children[:5]:
                lines.append(f"   └─ {child.signature} (L{child.line_start})")
            if len(symbol.children) > 5:
                lines.append(f"   └─ ... and {len(symbol.children) - 5} more")

        return ToolResultDisplay(
            success=True,
            message=result.summary,
            details={
                "path": result.path,
                "language": result.language,
                "outline": "\n".join(lines),
            },
        )

    @classmethod
    def get_status_text(cls) -> str:
        return "Analyzing code structure"
