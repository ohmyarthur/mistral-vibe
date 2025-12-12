Use `diff_file` to preview changes in a specific file.

**Features:**
- Shows additions and deletions
- Parses diff into hunks with line numbers
- Works with staged or unstaged changes
- Configurable context lines

**When to use:**
- Before committing to review changes
- Understanding what was modified
- Verifying your edits are correct
- Comparing staged vs unstaged

**Examples:**
- Unstaged changes: `diff_file(path="main.py")`
- Staged changes: `diff_file(path="main.py", staged=true)`
- More context: `diff_file(path="main.py", context_lines=5)`

**Output includes:**
- Addition/deletion counts
- Diff hunks with line numbers
- Original and new line content

**Best practice:** Use before commit_suggestion to verify changes are as expected.
