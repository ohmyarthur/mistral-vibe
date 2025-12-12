Use `find_by_name` to search for files and directories by name pattern.

- Uses glob pattern matching (e.g., `*.py`, `test_*`, `*config*`)
- Recursively searches directories up to max_depth
- Can filter by type: `file`, `directory`, or `any`
- Auto-excludes common junk: `.git`, `node_modules`, `__pycache__`, etc.

**Examples:**
- Find all Python files: `pattern="*.py"`
- Find test files: `pattern="test_*.py"`
- Find config files: `pattern="*config*"`
- Find directories named 'src': `pattern="src", file_type="directory"`

**When to use:**
- Locating files in unfamiliar codebases
- Finding all files of a certain type
- Discovering project structure quickly

**Better than bash `find` because:**
- Structured output with file types and sizes
- Smart defaults (excludes junk directories)
- Cross-platform consistent behavior
