Use `view_file_outline` to understand code structure before making edits.

**Returns:**
- Classes with their methods
- Functions with signatures and line numbers
- Docstrings (first 200 chars)
- Total line count

**When to use:**
- Before editing a file you haven't seen
- Understanding class hierarchies
- Finding the right function to modify
- Getting an overview of large files

**Example output:**
```
📄 agent.py (python, 986 lines)
   5 classes, 12 functions, 45 methods

🔷 class Agent (L45-986)
   └─ def __init__(self, config: VibeConfig) (L50)
   └─ async def act(self, message: str) (L120)
   └─ def compact(self) (L450)

🔹 def load_config() -> VibeConfig (L15-42)
```

**Better than reading full file because:**
- Shows structure without noise
- Includes line numbers for navigation
- Helps plan edits more precisely
