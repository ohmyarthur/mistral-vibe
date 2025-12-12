Use `multi_edit` for surgical multi-file code changes with atomic transactions.

## Key Features

- **5-tier matching**: Exact → Normalized → Anchored → Line-range → Fuzzy
- **Atomic transactions**: All succeed or all rollback
- **Conflict detection**: Hash-based file change detection
- **Dry-run default**: Always preview before applying
- **Backup creation**: Automatic .bak files
- **Reject files**: Failed edits preserved for manual review

## Modes

| Mode | Behavior |
|------|----------|
| `dry_run=True` (default) | Preview only, show diff |
| `check_only=True` | Validate matches, no diff |
| `dry_run=False` | Actually apply changes |

## Example Usage

```json
{
  "files": [
    {
      "path": "config.py",
      "edits": [
        {
          "search": "DEBUG = True",
          "replace": "DEBUG = False"
        }
      ]
    }
  ],
  "dry_run": true
}
```

## Matching Tiers

1. **Exact** (1.0): Byte-for-byte match
2. **Normalized** (0.95): Whitespace-tolerant
3. **Anchored** (0.90): Use context_before/after
4. **Line-range** (0.85): Target specific lines
5. **Fuzzy** (diagnostic): Suggest only, never auto-apply

## Safety

- Abort on any failure (fail_fast=True)
- Check for merge/rebase conflicts
- Hash verification before apply
- Backup files created automatically
- Full rollback on error

## Best Practices

1. Always use `dry_run=True` first
2. Review the diff preview
3. Then call with `dry_run=False` to apply
4. Use `context_before`/`context_after` for precision
5. Use `line_start`/`line_end` for targeted edits
