from __future__ import annotations

import pytest
import pytest_asyncio

from vibe.core.tools.builtins.git_status import (
    GitStatus,
    GitStatusArgs,
    GitStatusState,
    GitStatusToolConfig,
)


@pytest.fixture
def git_tool(tmp_path):
    config = GitStatusToolConfig(workdir=tmp_path)
    return GitStatus(config=config, state=GitStatusState())


@pytest_asyncio.fixture
async def git_repo(tmp_path):
    import asyncio

    async def run(*args):
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=tmp_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()

    await run("git", "init")
    await run("git", "config", "user.email", "test@test.com")
    await run("git", "config", "user.name", "Test")

    (tmp_path / "file.txt").write_text("content")
    await run("git", "add", "file.txt")
    await run("git", "commit", "-m", "Initial commit")

    return tmp_path


@pytest.mark.asyncio
async def test_detects_non_git_repo(git_tool):
    result = await git_tool.run(GitStatusArgs())

    assert result.is_git_repo is False
    assert "not a git" in result.summary.lower()


@pytest.mark.asyncio
async def test_detects_git_repo(tmp_path, git_repo):
    config = GitStatusToolConfig(workdir=git_repo)
    tool = GitStatus(config=config, state=GitStatusState())

    result = await tool.run(GitStatusArgs())

    assert result.is_git_repo is True


@pytest.mark.asyncio
async def test_gets_branch_name(tmp_path, git_repo):
    config = GitStatusToolConfig(workdir=git_repo)
    tool = GitStatus(config=config, state=GitStatusState())

    result = await tool.run(GitStatusArgs())

    assert result.branch in ["main", "master"]


@pytest.mark.asyncio
async def test_detects_untracked_files(tmp_path, git_repo):
    (git_repo / "untracked.txt").write_text("new file")

    config = GitStatusToolConfig(workdir=git_repo)
    tool = GitStatus(config=config, state=GitStatusState())

    result = await tool.run(GitStatusArgs(include_untracked=True))

    assert "untracked.txt" in result.untracked


@pytest.mark.asyncio
async def test_excludes_untracked_when_disabled(tmp_path, git_repo):
    (git_repo / "untracked.txt").write_text("new file")

    config = GitStatusToolConfig(workdir=git_repo)
    tool = GitStatus(config=config, state=GitStatusState())

    result = await tool.run(GitStatusArgs(include_untracked=False))

    assert len(result.untracked) == 0


@pytest.mark.asyncio
async def test_detects_modified_files(tmp_path, git_repo):
    (git_repo / "file.txt").write_text("modified content")

    config = GitStatusToolConfig(workdir=git_repo)
    tool = GitStatus(config=config, state=GitStatusState())

    result = await tool.run(GitStatusArgs())

    assert len(result.unstaged) > 0
    assert any(f.path == "file.txt" for f in result.unstaged)


@pytest.mark.asyncio
async def test_detects_staged_files(tmp_path, git_repo):
    import asyncio

    (git_repo / "new_file.txt").write_text("new content")
    proc = await asyncio.create_subprocess_exec(
        "git", "add", "new_file.txt", cwd=git_repo
    )
    await proc.communicate()

    config = GitStatusToolConfig(workdir=git_repo)
    tool = GitStatus(config=config, state=GitStatusState())

    result = await tool.run(GitStatusArgs())

    assert len(result.staged) > 0
    assert any(f.path == "new_file.txt" for f in result.staged)


@pytest.mark.asyncio
async def test_generates_clean_summary(tmp_path, git_repo):
    config = GitStatusToolConfig(workdir=git_repo)
    tool = GitStatus(config=config, state=GitStatusState())

    result = await tool.run(GitStatusArgs())

    assert "clean" in result.summary.lower() or (
        result.branch and result.branch in result.summary
    )


@pytest.mark.asyncio
async def test_generates_summary_with_changes(tmp_path, git_repo):
    (git_repo / "file.txt").write_text("modified")
    (git_repo / "untracked.txt").write_text("new")

    config = GitStatusToolConfig(workdir=git_repo)
    tool = GitStatus(config=config, state=GitStatusState())

    result = await tool.run(GitStatusArgs())

    assert "modified" in result.summary.lower() or "untracked" in result.summary.lower()


def test_get_call_display():
    from vibe.core.types import ToolCallEvent

    args = GitStatusArgs()
    event = ToolCallEvent(
        tool_call_id="test", tool_name="git_status", tool_class=GitStatus, args=args
    )

    display = GitStatus.get_call_display(event)
    assert "git_status" in display.summary
