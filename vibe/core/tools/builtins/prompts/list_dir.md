Use `list_dir` to explore directory contents and understand project structure.

- Returns structured list of files and directories with sizes
- Directories show child count, files show size in human-readable format
- Sorted: directories first, then files alphabetically
- By default excludes hidden files (use `include_hidden=true` to see them)

**When to use:**
- Understanding project layout
- Finding files without knowing exact names
- Exploring unfamiliar codebases

**Better than bash `ls` because:**
- Structured output (not just text)
- Shows file sizes and directory item counts
- Consistent cross-platform behavior
