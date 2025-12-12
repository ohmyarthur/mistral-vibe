Use `test_run` to execute pytest tests and verify code changes.

**Features:**
- Run all tests or filter by pattern
- Fail-fast mode for quick feedback
- Structured results with pass/fail counts
- Shows failed test names and locations

**When to use:**
- After making code changes
- Before suggesting commits
- To verify fixes work
- Run specific test files

**Examples:**
- Run all tests: `test_run()`
- Run specific file: `test_run(path="tests/test_auth.py")`
- Filter by name: `test_run(pattern="test_login")`
- Quick check: `test_run(fail_fast=true)`

**Output includes:**
- Pass/fail/skip counts
- Duration
- Failed test details
- Full test output

**Best practice:** Always run tests after making changes, before suggesting commits.
