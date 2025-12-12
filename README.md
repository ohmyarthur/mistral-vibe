# Mistral Vibe (Experimental Fork)

> ⚠️ **WARNING: This is an experimental playground fork!**
>
> This repo contains heavy customizations and additional tooling not present in the original.
> Nothing special here - just personal experimentation.

## What's Different?

Custom tools added:
- `list_dir` - Directory listing
- `find_by_name` - File search
- `view_file_outline` - Code structure analysis
- `git_status` - Git integration
- `test_run` - Pytest execution
- `commit_suggestion` - AI commit messages
- `diff_file` - File diff preview
- `multi_edit` - Atomic multi-file editing with 5-tier matching

## Quick Setup

```bash
# Clone this fork
git clone https://github.com/ohmyarthur/mistral-vibe.git
cd mistral-vibe

# Install with uv
uv sync

# Set your API key
export MISTRAL_API_KEY=your_key_here

# Run
uv run vibe
```

## Original Project

For the official Mistral Vibe, visit: https://github.com/mistralai/mistral-vibe

## License

Apache 2.0 (same as original)
