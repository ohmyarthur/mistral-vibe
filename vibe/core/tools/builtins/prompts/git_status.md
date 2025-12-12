Use `git_status` to check repository state before making changes.

**Returns:**
- Current branch name
- Ahead/behind remote count
- Staged files (ready to commit)
- Unstaged modified files
- Untracked files
- Stash count (optional)
- Merge conflict detection

**When to use:**
- Before starting work (check clean state)
- Before committing (see what's staged)
- Understanding current changes
- Checking for merge conflicts

**Better than `git status` because:**
- Structured output (not just text)
- Separate staged vs unstaged lists
- Includes ahead/behind tracking
- Conflict detection built-in

**Example:** Check status before suggesting commits, or to understand what the user has changed.
