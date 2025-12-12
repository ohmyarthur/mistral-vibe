Use `commit_suggestion` to generate commit messages from staged changes.

**Features:**
- Analyzes staged files (git add'd)
- Detects commit type (feat, fix, docs, test, chore)
- Generates conventional commit format
- Includes file change summary

**When to use:**
- After staging changes for commit
- To suggest commit message to user
- After completing a task

**Commit types detected:**
- `feat`: New features, additions
- `fix`: Bug fixes, small changes
- `test`: Test file changes
- `docs`: Documentation updates
- `chore`: Config, dependencies

**Styles:**
- `conventional`: "feat(scope): message"
- `simple`: "Add feature"
- `detailed`: Full file paths

**Best practice:**
1. Make changes
2. Run tests with `test_run`
3. Stage with bash `git add`
4. Use `commit_suggestion` to suggest message
