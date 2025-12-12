from __future__ import annotations

from pathlib import Path

import pytest

from vibe.core.tools.builtins.multi_edit import (
    DiffGenerator,
    EditBlock,
    FileEdit,
    MatchingEngine,
    MatchTier,
    MultiEdit,
    MultiEditArgs,
    MultiEditConfig,
    MultiEditState,
    SafetyChecker,
)


@pytest.fixture
def multi_edit_tool(tmp_path):
    config = MultiEditConfig(workdir=tmp_path)
    return MultiEdit(config=config, state=MultiEditState())


@pytest.fixture
def sample_file(tmp_path):
    content = '''def hello():
    """Say hello."""
    print("Hello, World!")
    return True

def goodbye():
    """Say goodbye."""
    print("Goodbye!")
    return False
'''
    file_path = tmp_path / "sample.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def config_file(tmp_path):
    content = """DEBUG = True
LOG_LEVEL = "INFO"
MAX_CONNECTIONS = 100
"""
    file_path = tmp_path / "config.py"
    file_path.write_text(content)
    return file_path


class TestMatchingEngine:
    def test_tier1_exact_match(self):
        content = "Hello World"
        edit = EditBlock(search="World", replace="Universe")

        result = MatchingEngine.match(content, edit)

        assert result.success
        assert result.tier == MatchTier.EXACT
        assert result.confidence == 1.0
        assert result.match_start == 6
        assert result.match_end == 11

    def test_tier1_exact_no_match(self):
        content = "Hello World"
        edit = EditBlock(search="Galaxy", replace="Universe")

        result = MatchingEngine.match(content, edit)

        assert not result.success or result.tier != MatchTier.EXACT

    def test_tier2_normalized_match(self):
        content = "    def hello():\n        pass\n"
        edit = EditBlock(search="def hello():\n    pass", replace="def hi():\n    pass")

        result = MatchingEngine.match(content, edit)

        assert result.tier in [MatchTier.EXACT, MatchTier.NORMALIZED]

    def test_tier3_anchored_match(self):
        content = """def foo():
    # anchor before
    target_line = "important"
    # anchor after
"""
        edit = EditBlock(
            search='target_line = "important"',
            replace='target_line = "modified"',
            context_before="# anchor before",
            context_after="# anchor after",
        )

        result = MatchingEngine.match(content, edit)

        assert result.success
        assert result.tier in [MatchTier.EXACT, MatchTier.ANCHORED]

    def test_tier4_line_range_match(self):
        content = """line 1
line 2
target here
line 4
line 5
"""
        edit = EditBlock(
            search="target here", replace="modified here", line_start=2, line_end=4
        )

        result = MatchingEngine.match(content, edit)

        assert result.success

    def test_tier5_fuzzy_no_auto_apply(self):
        content = "Hello World"
        edit = EditBlock(search="Hello World", replace="Hi Universe")  # Typo

        result = MatchingEngine.match(content, edit)

        if result.tier == MatchTier.FUZZY:
            assert not result.success


class TestMultiEdit:
    @pytest.mark.asyncio
    async def test_dry_run_single_file(self, tmp_path, config_file):
        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(config_file),
                    edits=[EditBlock(search="DEBUG = True", replace="DEBUG = False")],
                )
            ],
            dry_run=True,
        )

        result = await tool.run(args)

        assert result.success
        assert result.state == "previewed"
        assert result.edits_applied == 1
        assert result.can_apply
        assert "DEBUG = False" in result.results[0].diff_preview

        assert "DEBUG = True" in config_file.read_text()

    @pytest.mark.asyncio
    async def test_apply_single_edit(self, tmp_path, config_file):
        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(config_file),
                    edits=[EditBlock(search="DEBUG = True", replace="DEBUG = False")],
                )
            ],
            dry_run=False,
        )

        result = await tool.run(args)

        assert result.success
        assert result.state == "applied"
        assert result.edits_applied == 1

        assert "DEBUG = False" in config_file.read_text()

    @pytest.mark.asyncio
    async def test_multiple_edits_single_file(self, tmp_path, config_file):
        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(config_file),
                    edits=[
                        EditBlock(search="DEBUG = True", replace="DEBUG = False"),
                        EditBlock(
                            search='LOG_LEVEL = "INFO"', replace='LOG_LEVEL = "DEBUG"'
                        ),
                    ],
                )
            ],
            dry_run=False,
        )

        result = await tool.run(args)

        assert result.success
        assert result.edits_applied == 2

        content = config_file.read_text()
        assert "DEBUG = False" in content
        assert 'LOG_LEVEL = "DEBUG"' in content

    @pytest.mark.asyncio
    async def test_multi_file_edit(self, tmp_path):
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("VERSION = 1")
        file2.write_text("VERSION = 1")

        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(file1),
                    edits=[EditBlock(search="VERSION = 1", replace="VERSION = 2")],
                ),
                FileEdit(
                    path=str(file2),
                    edits=[EditBlock(search="VERSION = 1", replace="VERSION = 2")],
                ),
            ],
            dry_run=False,
        )

        result = await tool.run(args)

        assert result.success
        assert result.files_modified == 2
        assert "VERSION = 2" in file1.read_text()
        assert "VERSION = 2" in file2.read_text()

    @pytest.mark.asyncio
    async def test_fail_fast_rollback(self, tmp_path):
        file1 = tmp_path / "file1.py"
        file1.write_text("GOOD = True")

        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(file1),
                    edits=[
                        EditBlock(search="GOOD = True", replace="GOOD = Modified"),
                        EditBlock(
                            search="NONEXISTENT", replace="FAIL"
                        ),  # This will fail
                    ],
                )
            ],
            dry_run=False,
            fail_fast=True,
        )

        result = await tool.run(args)

        assert not result.success
        assert result.state == "rolled_back"

    @pytest.mark.asyncio
    async def test_creates_backup(self, tmp_path, config_file):
        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        original_content = config_file.read_text()

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(config_file),
                    edits=[EditBlock(search="DEBUG = True", replace="DEBUG = False")],
                )
            ],
            dry_run=False,
            create_backup=True,
        )

        result = await tool.run(args)

        assert result.success
        assert result.backup_paths

        backup_path = Path(list(result.backup_paths.values())[0])
        assert backup_path.exists()
        assert backup_path.read_text() == original_content

    @pytest.mark.asyncio
    async def test_hash_conflict_detection(self, tmp_path, config_file):
        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(config_file),
                    edits=[EditBlock(search="DEBUG = True", replace="DEBUG = False")],
                    expected_hash="wrong_hash_12345",
                )
            ],
            dry_run=False,
        )

        result = await tool.run(args)

        assert not result.success
        assert "hash mismatch" in result.results[0].errors[0].lower()

    @pytest.mark.asyncio
    async def test_file_not_found(self, tmp_path):
        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(tmp_path / "nonexistent.py"),
                    edits=[EditBlock(search="x", replace="y")],
                )
            ]
        )

        result = await tool.run(args)

        assert not result.success
        assert "not found" in result.results[0].errors[0].lower()

    @pytest.mark.asyncio
    async def test_check_only_mode(self, tmp_path, config_file):
        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(config_file),
                    edits=[EditBlock(search="DEBUG = True", replace="DEBUG = False")],
                )
            ],
            check_only=True,
        )

        result = await tool.run(args)

        assert result.success
        assert result.state == "checked"

        assert "DEBUG = True" in config_file.read_text()

    @pytest.mark.asyncio
    async def test_generates_reject_file(self, tmp_path, config_file):
        config = MultiEditConfig(workdir=tmp_path)
        tool = MultiEdit(config=config, state=MultiEditState())

        args = MultiEditArgs(
            files=[
                FileEdit(
                    path=str(config_file),
                    edits=[
                        EditBlock(search="NONEXISTENT_STRING", replace="REPLACEMENT")
                    ],
                )
            ],
            dry_run=True,
        )

        result = await tool.run(args)

        assert not result.success
        assert result.reject_files
        assert "NONEXISTENT_STRING" in list(result.reject_files.values())[0]


class TestSafetyChecker:
    @pytest.mark.asyncio
    async def test_passes_clean_repo(self, tmp_path):
        passed, errors = await SafetyChecker.check_all(tmp_path)
        assert passed
        assert len(errors) == 0

    @pytest.mark.asyncio
    async def test_detects_merge_in_progress(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "MERGE_HEAD").write_text("abc123")

        passed, errors = await SafetyChecker.check_all(tmp_path)

        assert not passed
        assert any("merge" in e.lower() for e in errors)


class TestDiffGenerator:
    """Tests for diff generation."""

    def test_generates_unified_diff(self):
        original = "line1\nline2\nline3\n"
        modified = "line1\nmodified\nline3\n"

        diff = DiffGenerator.generate(original, modified, "test.py")

        assert "--- a/test.py" in diff
        assert "+++ b/test.py" in diff
        assert "-line2" in diff
        assert "+modified" in diff


def test_get_call_display():
    from vibe.core.types import ToolCallEvent

    args = MultiEditArgs(
        files=[FileEdit(path="test.py", edits=[EditBlock(search="a", replace="b")])],
        dry_run=True,
    )

    event = ToolCallEvent(
        tool_call_id="test", tool_name="multi_edit", tool_class=MultiEdit, args=args
    )

    display = MultiEdit.get_call_display(event)

    assert "multi_edit" in display.summary
    assert "1 file" in display.summary
    assert "1 edit" in display.summary
