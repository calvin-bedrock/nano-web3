"""Spawn tool for creating background subagents."""

from typing import Any, TYPE_CHECKING, Awaitable, Callable

from nanobot.agent.tools.base import Tool
from nanobot.bus.events import OutboundMessage

if TYPE_CHECKING:
    from nanobot.agent.subagent import SubagentManager


class SpawnTool(Tool):
    """
    Tool to spawn a subagent for background task execution.

    The subagent runs asynchronously and announces its result back
    to the main agent when complete.
    """

    def __init__(self, manager: "SubagentManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._send_callback: Callable[[OutboundMessage], Awaitable[str | None]] | None = None

    def set_context(self, channel: str, chat_id: str) -> None:
        """Set the origin context for subagent announcements."""
        self._origin_channel = channel
        self._origin_chat_id = chat_id

    def set_send_callback(self, callback: Callable[[OutboundMessage], Awaitable[str | None]]) -> None:
        """Set the callback for sending placeholder messages."""
        self._send_callback = callback

    @property
    def name(self) -> str:
        return "spawn"

    @property
    def description(self) -> str:
        return (
            "Spawn a subagent to handle a task in the background. "
            "Use this for complex or time-consuming tasks that can run independently. "
            "The subagent will complete the task and report back when done."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The task for the subagent to complete",
                },
                "label": {
                    "type": "string",
                    "description": "Optional short label for the task (for display)",
                },
            },
            "required": ["task"],
        }

    async def execute(self, task: str, label: str | None = None, **kwargs: Any) -> str:
        """Spawn a subagent to execute the given task."""
        from loguru import logger
        display_label = label or task[:30] + ("..." if len(task) > 30 else "")

        # Send placeholder message if send_callback is available and not CLI
        message_id: str | None = None
        logger.info(f"[Spawn] channel={self._origin_channel}, has_callback={self._send_callback is not None}")

        if self._send_callback and self._origin_channel != "cli":
            placeholder = f"⏳ *Processing:* {display_label}"
            msg = OutboundMessage(
                channel=self._origin_channel,
                chat_id=self._origin_chat_id,
                content=placeholder,
                track_message_id=True
            )
            # Properly await the async send_callback
            result = await self._send_callback(msg)
            message_id = result
            logger.info(f"[Spawn] Placeholder sent, message_id={message_id}")
        else:
            logger.info(f"[Spawn] Skipping placeholder (callback={self._send_callback is not None}, channel={self._origin_channel})")

        return await self._manager.spawn(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            placeholder_message_id=message_id,
        )
