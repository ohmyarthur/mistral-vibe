from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import Static


class CollapsibleSection(Static):
    """A collapsible section with a clickable header and expandable content.

    The header displays an arrow indicator (▶ collapsed, ▼ expanded) followed by
    the title. Clicking the header toggles the section's expanded state.
    """

    expanded: reactive[bool] = reactive(False)

    ARROW_COLLAPSED = "▶"
    ARROW_EXPANDED = "▼"

    class Toggled(Message):
        def __init__(self, section: CollapsibleSection, expanded: bool) -> None:
            self.section = section
            self.expanded = expanded
            super().__init__()

    def __init__(
        self,
        title: str,
        *,
        expanded: bool = False,
        icon: str = "",
        status_style: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._icon = icon
        self._status_style = status_style
        self.expanded = expanded
        self._header: Static | None = None
        self._content_container: Vertical | None = None

    def compose(self) -> ComposeResult:
        self._header = Static(self._render_header(), classes="collapsible-header")
        yield self._header
        self._content_container = Vertical(classes="collapsible-content")
        if not self.expanded:
            self._content_container.styles.display = "none"
        yield self._content_container

    def _render_header(self) -> str:
        arrow = self.ARROW_EXPANDED if self.expanded else self.ARROW_COLLAPSED
        icon_part = f"{self._icon} " if self._icon else ""
        if self._status_style:
            return f"[{self._status_style}]{arrow}[/] {icon_part}{self._title}"
        return f"{arrow} {icon_part}{self._title}"

    def watch_expanded(self, expanded: bool) -> None:
        if self._header:
            self._header.update(self._render_header())
        if self._content_container:
            self._content_container.styles.display = "block" if expanded else "none"

    async def on_click(self, event: Any) -> None:
        if self._header and event.y == 0:
            self.expanded = not self.expanded
            self.post_message(self.Toggled(self, self.expanded))
            event.stop()

    def update_title(self, title: str) -> None:
        self._title = title
        if self._header:
            self._header.update(self._render_header())

    def update_icon(self, icon: str) -> None:
        self._icon = icon
        if self._header:
            self._header.update(self._render_header())

    def update_status_style(self, style: str) -> None:
        self._status_style = style
        if self._header:
            self._header.update(self._render_header())

    @property
    def content_container(self) -> Vertical | None:
        return self._content_container

    async def set_content(self, *widgets: Static) -> None:
        if self._content_container:
            await self._content_container.remove_children()
            for widget in widgets:
                await self._content_container.mount(widget)


class ToolSection(CollapsibleSection):
    """A collapsible section styled for tool calls and results."""

    def __init__(
        self,
        title: str,
        *,
        expanded: bool = False,
        success: bool | None = None,
        pending: bool = False,
        **kwargs: Any,
    ) -> None:
        icon = self._get_status_icon(success, pending)
        status_style = self._get_status_style(success, pending)
        super().__init__(
            title,
            expanded=expanded,
            icon=icon,
            status_style=status_style,
            **kwargs,
        )
        self._success = success
        self._pending = pending

    def _get_status_icon(self, success: bool | None, pending: bool) -> str:
        if pending:
            return "○"
        if success is None:
            return "●"
        return "●" if success else "●"

    def _get_status_style(self, success: bool | None, pending: bool) -> str:
        if pending:
            return "$text-muted"
        if success is None:
            return "$foreground"
        return "$success" if success else "$error"

    def set_status(self, success: bool | None = None, pending: bool = False) -> None:
        self._success = success
        self._pending = pending
        self.update_icon(self._get_status_icon(success, pending))
        self.update_status_style(self._get_status_style(success, pending))


class ThinkingSection(CollapsibleSection):
    """A collapsible section for displaying AI thinking/reasoning process."""

    def __init__(self, title: str = "Thinking", **kwargs: Any) -> None:
        super().__init__(title, icon="◐", status_style="$warning", **kwargs)
        self._thinking_lines: list[str] = []

    async def add_thinking_line(self, line: str) -> None:
        if line in self._thinking_lines:
            return
        self._thinking_lines.append(line)
        await self._refresh_content()

    async def _refresh_content(self) -> None:
        if self._content_container:
            await self._content_container.remove_children()
            for line in self._thinking_lines:
                await self._content_container.mount(
                    Static(f"  {line}", markup=False, classes="thinking-line")
                )

    def clear(self) -> None:
        self._thinking_lines.clear()


class TodoSection(CollapsibleSection):
    """A collapsible section for displaying task/todo items."""

    def __init__(self, title: str = "Tasks", **kwargs: Any) -> None:
        super().__init__(title, icon="☐", status_style="$primary", **kwargs)
        self._todos: list[dict[str, Any]] = []

    async def update_todos(self, todos: list[dict[str, Any]]) -> None:
        self._todos = todos
        await self._refresh_content()
        self._update_header_stats()

    def _update_header_stats(self) -> None:
        total = len(self._todos)
        completed = sum(1 for t in self._todos if t.get("status") == "completed")
        in_progress = sum(1 for t in self._todos if t.get("status") == "in_progress")

        if total == 0:
            self.update_title("Tasks")
            self.update_icon("☐")
            self.update_status_style("$text-muted")
        elif completed == total:
            self.update_title(f"Tasks ({completed}/{total})")
            self.update_icon("☑")
            self.update_status_style("$success")
        elif in_progress > 0:
            self.update_title(f"Tasks ({completed}/{total})")
            self.update_icon("◐")
            self.update_status_style("$warning")
        else:
            self.update_title(f"Tasks ({completed}/{total})")
            self.update_icon("☐")
            self.update_status_style("$primary")

    async def _refresh_content(self) -> None:
        if not self._content_container:
            return

        await self._content_container.remove_children()

        if not self._todos:
            await self._content_container.mount(
                Static("  No tasks", markup=False, classes="todo-empty")
            )
            return

        for todo in self._todos:
            content = todo.get("content", "")
            status = todo.get("status", "pending")
            icon = self._get_todo_icon(status)
            style_class = f"todo-{status}"
            await self._content_container.mount(
                Static(f"  {icon} {content}", markup=False, classes=style_class)
            )

    def _get_todo_icon(self, status: str) -> str:
        icons = {
            "pending": "☐",
            "in_progress": "◐",
            "completed": "☑",
            "cancelled": "☒",
        }
        return icons.get(status, "☐")
