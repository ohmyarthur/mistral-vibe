from __future__ import annotations

import pytest

from vibe.core.tools.base import BaseToolState, ToolError
from vibe.core.tools.builtins.list_dir import ListDir, ListDirArgs, ListDirToolConfig


@pytest.fixture
def list_dir_tool(tmp_path):
    config = ListDirToolConfig(workdir=tmp_path)
    return ListDir(config=config, state=BaseToolState())


@pytest.fixture
def populated_dir(tmp_path):
    (tmp_path / "file1.txt").write_text("hello")
    (tmp_path / "file2.py").write_text("print('hi')")
    (tmp_path / "subdir").mkdir()
    (tmp_path / "subdir" / "nested.txt").write_text("nested")
    (tmp_path / ".hidden").write_text("hidden")
    return tmp_path


@pytest.mark.asyncio
async def test_lists_empty_directory(list_dir_tool, tmp_path):
    result = await list_dir_tool.run(ListDirArgs(path=str(tmp_path)))

    assert result.path == str(tmp_path)
    assert result.entries == []
    assert result.total_files == 0
    assert result.total_dirs == 0
    assert result.was_truncated is False


@pytest.mark.asyncio
async def test_lists_files_and_directories(tmp_path, populated_dir):
    config = ListDirToolConfig(workdir=tmp_path)
    tool = ListDir(config=config, state=BaseToolState())

    result = await tool.run(ListDirArgs(path=str(populated_dir)))

    assert result.total_files == 2
    assert result.total_dirs == 1
    names = [e.name for e in result.entries]
    assert "file1.txt" in names
    assert "file2.py" in names
    assert "subdir" in names
    assert ".hidden" not in names


@pytest.mark.asyncio
async def test_includes_hidden_files_when_requested(tmp_path, populated_dir):
    config = ListDirToolConfig(workdir=tmp_path)
    tool = ListDir(config=config, state=BaseToolState())

    result = await tool.run(ListDirArgs(path=str(populated_dir), include_hidden=True))

    names = [e.name for e in result.entries]
    assert ".hidden" in names


@pytest.mark.asyncio
async def test_shows_file_sizes(tmp_path, populated_dir):
    config = ListDirToolConfig(workdir=tmp_path)
    tool = ListDir(config=config, state=BaseToolState())

    result = await tool.run(ListDirArgs(path=str(populated_dir)))

    file_entry = next(e for e in result.entries if e.name == "file1.txt")
    assert file_entry.size == 5
    assert file_entry.is_dir is False


@pytest.mark.asyncio
async def test_shows_directory_children_count(tmp_path, populated_dir):
    config = ListDirToolConfig(workdir=tmp_path)
    tool = ListDir(config=config, state=BaseToolState())

    result = await tool.run(ListDirArgs(path=str(populated_dir)))

    dir_entry = next(e for e in result.entries if e.name == "subdir")
    assert dir_entry.children_count == 1
    assert dir_entry.is_dir is True


@pytest.mark.asyncio
async def test_raises_error_for_nonexistent_directory(list_dir_tool):
    with pytest.raises(ToolError) as err:
        await list_dir_tool.run(ListDirArgs(path="/nonexistent/path"))

    assert "not found" in str(err.value).lower()


@pytest.mark.asyncio
async def test_raises_error_for_file_path(tmp_path, populated_dir):
    config = ListDirToolConfig(workdir=tmp_path)
    tool = ListDir(config=config, state=BaseToolState())

    with pytest.raises(ToolError) as err:
        await tool.run(ListDirArgs(path=str(populated_dir / "file1.txt")))

    assert "not a directory" in str(err.value).lower()


@pytest.mark.asyncio
async def test_truncates_when_exceeds_max_entries(tmp_path):
    for i in range(10):
        (tmp_path / f"file{i}.txt").write_text(f"content {i}")

    config = ListDirToolConfig(workdir=tmp_path, max_entries=5)
    tool = ListDir(config=config, state=BaseToolState())

    result = await tool.run(ListDirArgs(path=str(tmp_path)))

    assert len(result.entries) == 5
    assert result.was_truncated is True


@pytest.mark.asyncio
async def test_sorts_directories_first(tmp_path, populated_dir):
    config = ListDirToolConfig(workdir=tmp_path)
    tool = ListDir(config=config, state=BaseToolState())

    result = await tool.run(ListDirArgs(path=str(populated_dir)))

    assert result.entries[0].is_dir is True
    assert result.entries[0].name == "subdir"


def test_get_call_display():
    from vibe.core.types import ToolCallEvent

    args = ListDirArgs(path="/some/path", include_hidden=True)
    event = ToolCallEvent(
        tool_call_id="test",
        tool_name="list_dir",
        tool_class=ListDir,
        args=args,
    )

    display = ListDir.get_call_display(event)

    assert "list_dir" in display.summary
    assert "/some/path" in display.summary


def test_format_size():
    assert ListDir._format_size(100) == "100B"
    assert ListDir._format_size(1024) == "1.0KB"
    assert ListDir._format_size(1024 * 1024) == "1.0MB"
    assert ListDir._format_size(1024 * 1024 * 1024) == "1.0GB"
