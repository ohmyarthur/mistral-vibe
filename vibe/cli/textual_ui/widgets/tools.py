from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from vibe.cli.textual_ui.renderers import get_renderer
from vibe.cli.textual_ui.widgets.collapsible import ToolSection
from vibe.core.tools.ui import ToolUIDataAdapter
from vibe.core.types import ToolCallEvent, ToolResultEvent


class ToolCallMessage(Static):
    """A tool call message with collapsible details."""

    def __init__(self, event: ToolCallEvent) -> None:
        self.event = event
        self._success: bool | None = None
        self._pending = True
        self._section: ToolSection | None = None
        super().__init__()
        self.add_class("tool-call")

    def compose(self) -> ComposeResult:
        title = self._get_title()
        self._section = ToolSection(
            title,
            expanded=False,
            success=None,
            pending=True,
            classes="tool-section pending",
        )
        yield self._section

    def _get_title(self) -> str:
        if not self.event.tool_class:
            return f"{self.event.tool_name}"

        adapter = ToolUIDataAdapter(self.event.tool_class)
        display = adapter.get_call_display(self.event)
        return display.summary

    def stop_blinking(self, success: bool = True) -> None:
        self._success = success
        self._pending = False
        if self._section:
            self._section.set_status(success=success, pending=False)
            self._section.remove_class("pending")
            self._section.add_class("success" if success else "error")


class ToolResultMessage(Static):
    """A tool result message with collapsible content."""

    def __init__(
        self,
        event: ToolResultEvent,
        call_widget: ToolCallMessage | None = None,
        collapsed: bool = True,
    ) -> None:
        self.event = event
        self.call_widget = call_widget
        self.collapsed = collapsed
        self._content_container: Vertical | None = None

        super().__init__()
        self.add_class("tool-result")

    def compose(self) -> ComposeResult:
        self._content_container = Vertical(classes="tool-content")
        yield self._content_container

    async def on_mount(self) -> None:
        if self.call_widget:
            success = not self.event.error and not self.event.skipped
            self.call_widget.stop_blinking(success=success)
        await self.render_result()

    async def render_result(self) -> None:
        if not self._content_container:
            return

        await self._content_container.remove_children()

        if self.event.error:
            self.add_class("error-text")
            await self._render_error()
            return

        if self.event.skipped:
            self.add_class("warning-text")
            await self._render_skipped()
            return

        self.remove_class("error-text")
        self.remove_class("warning-text")
        await self._render_success()

    async def _render_error(self) -> None:
        if not self._content_container:
            return

        if self.collapsed:
            await self._content_container.mount(
                Static("Error (click to expand)", markup=False)
            )
        else:
            await self._content_container.mount(
                Static(f"Error: {self.event.error}", markup=False)
            )

    async def _render_skipped(self) -> None:
        if not self._content_container:
            return

        reason = self.event.skip_reason or "User skipped"
        if self.collapsed:
            await self._content_container.mount(
                Static("Skipped (click to expand)", markup=False)
            )
        else:
            await self._content_container.mount(
                Static(f"Skipped: {reason}", markup=False)
            )

    async def _render_success(self) -> None:
        if not self._content_container:
            return

        adapter = ToolUIDataAdapter(self.event.tool_class)
        display = adapter.get_result_display(self.event)

        renderer = get_renderer(self.event.tool_name)
        widget_class, data = renderer.get_result_widget(display, self.collapsed)

        result_widget = widget_class(data, collapsed=self.collapsed)
        await self._content_container.mount(result_widget)

    async def on_click(self, event: Any) -> None:
        await self.toggle_collapsed()
        event.stop()

    async def set_collapsed(self, collapsed: bool) -> None:
        if self.collapsed != collapsed:
            self.collapsed = collapsed
            await self.render_result()

    async def toggle_collapsed(self) -> None:
        self.collapsed = not self.collapsed
        await self.render_result()
