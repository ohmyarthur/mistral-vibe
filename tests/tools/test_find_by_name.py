from __future__ import annotations

import pytest

from vibe.core.tools.base import ToolError
from vibe.core.tools.builtins.find_by_name import (
    FindByName,
    FindByNameArgs,
    FindByNameState,
    FindByNameToolConfig,
)


@pytest.fixture
def find_tool(tmp_path):
    config = FindByNameToolConfig(workdir=tmp_path)
    return FindByName(config=config, state=FindByNameState())


@pytest.fixture
def project_structure(tmp_path):
    (tmp_path / "main.py").write_text("print('main')")
    (tmp_path / "utils.py").write_text("print('utils')")
    (tmp_path / "test_main.py").write_text("print('test')")
    (tmp_path / "README.md").write_text("# Readme")
    (tmp_path / "config.json").write_text("{}")

    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('app')")
    (src / "helpers.py").write_text("print('helpers')")

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_app.py").write_text("print('test_app')")

    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("git config")

    (tmp_path / ".hidden.py").write_text("hidden")

    return tmp_path


@pytest.mark.asyncio
async def test_finds_python_files(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(FindByNameArgs(pattern="*.py", path=str(project_structure)))

    assert result.total_matches >= 5
    names = [m.name for m in result.matches]
    assert "main.py" in names
    assert "utils.py" in names
    assert "app.py" in names


@pytest.mark.asyncio
async def test_finds_test_files(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(
        FindByNameArgs(pattern="test_*.py", path=str(project_structure))
    )

    names = [m.name for m in result.matches]
    assert "test_main.py" in names
    assert "test_app.py" in names
    assert "main.py" not in names


@pytest.mark.asyncio
async def test_excludes_git_directory(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(FindByNameArgs(pattern="*", path=str(project_structure)))

    paths = [m.path for m in result.matches]
    assert not any(".git" in p for p in paths)


@pytest.mark.asyncio
async def test_excludes_hidden_files_by_default(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(FindByNameArgs(pattern="*.py", path=str(project_structure)))

    names = [m.name for m in result.matches]
    assert ".hidden.py" not in names


@pytest.mark.asyncio
async def test_includes_hidden_files_when_requested(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(
        FindByNameArgs(pattern="*.py", path=str(project_structure), include_hidden=True)
    )

    names = [m.name for m in result.matches]
    assert ".hidden.py" in names


@pytest.mark.asyncio
async def test_filters_by_file_type(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(
        FindByNameArgs(pattern="*", path=str(project_structure), file_type="directory")
    )

    assert all(m.is_dir for m in result.matches)
    names = [m.name for m in result.matches]
    assert "src" in names
    assert "tests" in names


@pytest.mark.asyncio
async def test_filters_files_only(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(
        FindByNameArgs(pattern="*", path=str(project_structure), file_type="file")
    )

    assert all(not m.is_dir for m in result.matches)


@pytest.mark.asyncio
async def test_respects_max_depth(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(
        FindByNameArgs(pattern="*.py", path=str(project_structure), max_depth=0)
    )

    names = [m.name for m in result.matches]
    assert "main.py" in names
    assert "app.py" not in names


@pytest.mark.asyncio
async def test_truncates_when_exceeds_max_results(tmp_path):
    for i in range(20):
        (tmp_path / f"file{i}.py").write_text(f"print({i})")

    config = FindByNameToolConfig(workdir=tmp_path, max_results=5)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(FindByNameArgs(pattern="*.py", path=str(tmp_path)))

    assert len(result.matches) == 5
    assert result.was_truncated is True


@pytest.mark.asyncio
async def test_raises_error_for_nonexistent_path(find_tool):
    with pytest.raises(ToolError) as err:
        await find_tool.run(FindByNameArgs(pattern="*.py", path="/nonexistent/path"))

    assert "not found" in str(err.value).lower()


@pytest.mark.asyncio
async def test_raises_error_for_file_path(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    with pytest.raises(ToolError) as err:
        await tool.run(
            FindByNameArgs(pattern="*.py", path=str(project_structure / "main.py"))
        )

    assert "not a directory" in str(err.value).lower()


@pytest.mark.asyncio
async def test_returns_relative_paths(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=project_structure)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(
        FindByNameArgs(pattern="app.py", path=str(project_structure))
    )

    assert len(result.matches) == 1
    assert result.matches[0].path == "src/app.py"


@pytest.mark.asyncio
async def test_includes_file_sizes(tmp_path, project_structure):
    config = FindByNameToolConfig(workdir=tmp_path)
    tool = FindByName(config=config, state=FindByNameState())

    result = await tool.run(
        FindByNameArgs(pattern="README.md", path=str(project_structure))
    )

    assert len(result.matches) == 1
    assert result.matches[0].size == 8


def test_get_call_display():
    from vibe.core.types import ToolCallEvent

    args = FindByNameArgs(pattern="*.py", path="/some/path")
    event = ToolCallEvent(
        tool_call_id="test", tool_name="find_by_name", tool_class=FindByName, args=args
    )

    display = FindByName.get_call_display(event)

    assert "find_by_name" in display.summary
    assert "*.py" in display.summary
