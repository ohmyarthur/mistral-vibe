from __future__ import annotations

import pytest

from vibe.core.tools.base import BaseToolState, ToolError
from vibe.core.tools.builtins.view_file_outline import (
    ViewFileOutline,
    ViewFileOutlineArgs,
    ViewFileOutlineToolConfig,
)


@pytest.fixture
def outline_tool(tmp_path):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    return ViewFileOutline(config=config, state=BaseToolState())


@pytest.fixture
def python_file(tmp_path):
    content = '''"""Module docstring."""

def hello(name: str) -> str:
    """Say hello."""
    return f"Hello, {name}!"

def add(a: int, b: int) -> int:
    return a + b

class Calculator:
    """A simple calculator."""

    def __init__(self, value: int = 0):
        self.value = value

    def add(self, x: int) -> int:
        """Add x to value."""
        return self.value + x

    async def async_method(self, x: int) -> int:
        return self.value + x

class AdvancedCalc(Calculator):
    """Extended calculator."""

    def multiply(self, x: int) -> int:
        return self.value * x
'''
    file_path = tmp_path / "example.py"
    file_path.write_text(content)
    return file_path


@pytest.mark.asyncio
async def test_parses_python_file(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file)))

    assert result.language == "python"
    assert result.total_lines > 0
    assert len(result.symbols) >= 4


@pytest.mark.asyncio
async def test_finds_functions(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file)))

    function_names = [s.name for s in result.symbols if s.type == "function"]
    assert "hello" in function_names
    assert "add" in function_names


@pytest.mark.asyncio
async def test_finds_classes(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file)))

    class_names = [s.name for s in result.symbols if s.type == "class"]
    assert "Calculator" in class_names
    assert "AdvancedCalc" in class_names


@pytest.mark.asyncio
async def test_finds_methods(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file)))

    calc_class = next(s for s in result.symbols if s.name == "Calculator")
    method_names = [c.name for c in calc_class.children]
    assert "__init__" in method_names
    assert "add" in method_names
    assert "async_method" in method_names


@pytest.mark.asyncio
async def test_includes_signatures(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file)))

    hello_func = next(s for s in result.symbols if s.name == "hello")
    assert "def hello(name: str) -> str" in hello_func.signature


@pytest.mark.asyncio
async def test_includes_docstrings(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file), include_docstrings=True))

    hello_func = next(s for s in result.symbols if s.name == "hello")
    assert hello_func.docstring == "Say hello."


@pytest.mark.asyncio
async def test_includes_line_numbers(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file)))

    hello_func = next(s for s in result.symbols if s.name == "hello")
    assert hello_func.line_start > 0
    assert hello_func.line_end >= hello_func.line_start


@pytest.mark.asyncio
async def test_respects_max_depth(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file), max_depth=1))

    calc_class = next(s for s in result.symbols if s.name == "Calculator")
    assert len(calc_class.children) == 0


@pytest.mark.asyncio
async def test_generates_summary(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file)))

    assert "classes" in result.summary
    assert "functions" in result.summary


@pytest.mark.asyncio
async def test_raises_error_for_nonexistent_file(outline_tool):
    with pytest.raises(ToolError) as err:
        await outline_tool.run(ViewFileOutlineArgs(path="/nonexistent/file.py"))

    assert "not found" in str(err.value).lower()


@pytest.mark.asyncio
async def test_raises_error_for_directory(tmp_path):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    with pytest.raises(ToolError) as err:
        await tool.run(ViewFileOutlineArgs(path=str(tmp_path)))

    assert "directory" in str(err.value).lower()


@pytest.mark.asyncio
async def test_raises_error_for_syntax_error(tmp_path):
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken(:\n    pass")

    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    with pytest.raises(ToolError) as err:
        await tool.run(ViewFileOutlineArgs(path=str(bad_file)))

    assert "syntax" in str(err.value).lower()


@pytest.mark.asyncio
async def test_handles_class_inheritance(tmp_path, python_file):
    config = ViewFileOutlineToolConfig(workdir=tmp_path)
    tool = ViewFileOutline(config=config, state=BaseToolState())

    result = await tool.run(ViewFileOutlineArgs(path=str(python_file)))

    adv_class = next(s for s in result.symbols if s.name == "AdvancedCalc")
    assert "Calculator" in adv_class.signature
