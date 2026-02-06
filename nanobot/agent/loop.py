"""Agent loop: the core processing engine."""

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import LLMProvider
from nanobot.agent.context import ContextBuilder
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool, EditFileTool, ListDirTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.agent.tools.web import WebSearchTool, WebFetchTool
from nanobot.agent.tools.message import MessageTool
from nanobot.agent.tools.spawn import SpawnTool
from nanobot.agent.tools.cron import CronTool
from nanobot.agent.subagent import SubagentManager
from nanobot.session.manager import SessionManager


class AgentLoop:
    """
    The agent loop is the core processing engine.
    
    It:
    1. Receives messages from the bus
    2. Builds context with history, memory, skills
    3. Calls the LLM
    4. Executes tool calls
    5. Sends responses back
    """
    
    def __init__(
        self,
        bus: MessageBus,
        provider: LLMProvider,
        workspace: Path,
        model: str | None = None,
        max_iterations: int = 20,
        brave_api_key: str | None = None,
        exec_config: "ExecToolConfig | None" = None,
        cron_service: "CronService | None" = None,
    ):
        from nanobot.config.schema import ExecToolConfig
        from nanobot.cron.service import CronService
        self.bus = bus
        self.provider = provider
        self.workspace = workspace
        self.model = model or provider.get_default_model()
        self.max_iterations = max_iterations
        self.brave_api_key = brave_api_key
        self.exec_config = exec_config or ExecToolConfig()
        self.cron_service = cron_service
        self._channel_manager = None  # Will be set by ChannelManager

        self.context = ContextBuilder(workspace)
        self.sessions = SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
        )

        self._running = False
        self._register_default_tools()

    def set_channel_manager(self, channel_manager) -> None:
        """Set the channel manager for immediate message sending."""
        self._channel_manager = channel_manager
        # Update spawn tool with immediate send callback
        spawn_tool = self.tools.get("spawn")
        if spawn_tool:
            spawn_tool.set_send_callback(self._send_immediate)

    async def _send_immediate(self, msg: "OutboundMessage") -> str | None:
        """Send a message immediately and return the message_id."""
        from loguru import logger
        logger.info(f"[SendImmediate] channel={msg.channel}, has_manager={self._channel_manager is not None}")
        if self._channel_manager:
            channel = self._channel_manager.get_channel(msg.channel)
            logger.info(f"[SendImmediate] got_channel={channel is not None}")
            if channel:
                result = await channel.send(msg)
                logger.info(f"[SendImmediate] send result={result}")
                return result
        # Fallback to async queue
        logger.info(f"[SendImmediate] Fallback to queue")
        await self.bus.publish_outbound(msg)
        return None
    
    def _register_default_tools(self) -> None:
        """Register the default set of tools."""
        # File tools
        self.tools.register(ReadFileTool())
        self.tools.register(WriteFileTool())
        self.tools.register(EditFileTool())
        self.tools.register(ListDirTool())
        
        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.exec_config.restrict_to_workspace,
        ))
        
        # Web tools
        self.tools.register(WebSearchTool(api_key=self.brave_api_key))
        self.tools.register(WebFetchTool())
        
        # Message tool
        message_tool = MessageTool(send_callback=self.bus.publish_outbound)
        self.tools.register(message_tool)

        # Spawn tool (for subagents)
        spawn_tool = SpawnTool(manager=self.subagents)
        spawn_tool.set_send_callback(self.bus.publish_outbound)
        self.tools.register(spawn_tool)
        
        # Cron tool (for scheduling)
        if self.cron_service:
            self.tools.register(CronTool(self.cron_service))
    
    async def run(self) -> None:
        """Run the agent loop, processing messages from the bus."""
        self._running = True
        logger.info("Agent loop started")
        
        while self._running:
            try:
                # Wait for next message
                msg = await asyncio.wait_for(
                    self.bus.consume_inbound(),
                    timeout=1.0
                )
                
                # Process it
                try:
                    response = await self._process_message(msg)
                    if response:
                        await self.bus.publish_outbound(response)
                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    # Send error response
                    await self.bus.publish_outbound(OutboundMessage(
                        channel=msg.channel,
                        chat_id=msg.chat_id,
                        content=f"Sorry, I encountered an error: {str(e)}"
                    ))
            except asyncio.TimeoutError:
                continue
    
    def stop(self) -> None:
        """Stop the agent loop."""
        self._running = False
        logger.info("Agent loop stopping")
    
    async def _analyze_development_task(self, content: str) -> dict[str, Any] | None:
        """
        Analyze if the user's request is a development task that needs approval.

        Returns:
            None if not a dev task, or dict with:
            - type: "dev_task"
            - analysis: What needs to be done
            - requirements: List of requirements (storage, web service, etc.)
            - estimated_cost: Estimated cost/time
            - steps: High-level implementation steps
        """
        analyze_prompt = [
            {"role": "system", "content": """Analyze if the user's request is a development task.

A development task involves:
- Creating/modifying code
- Setting up services or infrastructure
- Data processing pipelines
- Web applications or APIs
- Complex automation

Respond with JSON only:
{
    "is_dev_task": true/false,
    "analysis": "Brief description of what needs to be done",
    "requirements": ["list of requirements like database, web server, etc"],
    "estimated_cost": "estimated time/cost",
    "steps": ["step1", "step2", "..."]
}

If NOT a dev task, return {"is_dev_task": false}."""},
            {"role": "user", "content": content},
        ]

        try:
            response = await self.provider.chat(
                messages=analyze_prompt,
                tools=None,
                model=self.model,
                max_tokens=500,
                temperature=0.3
            )
            import json
            result = json.loads(response.content or "{}")

            if result.get("is_dev_task"):
                return {
                    "type": "dev_task",
                    "original_request": content,
                    "analysis": result.get("analysis", ""),
                    "requirements": result.get("requirements", []),
                    "estimated_cost": result.get("estimated_cost", ""),
                    "steps": result.get("steps", []),
                }
            return None
        except Exception as e:
            logger.warning(f"Failed to analyze dev task: {e}")
            return None

    async def _process_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a single inbound message.

        Args:
            msg: The inbound message to process.

        Returns:
            The response message, or None if no response needed.
        """
        # Handle system messages (subagent announces)
        # The chat_id contains the original "channel:chat_id" to route back to
        if msg.channel == "system":
            return await self._process_system_message(msg)

        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}")

        # Get or create session
        session = self.sessions.get_or_create(msg.session_key)

        # Check if there's a pending task awaiting approval
        if session.pending_task:
            return await self._handle_task_approval(msg, session)

        # Check if this is a development task that needs approval
        dev_task = await self._analyze_development_task(msg.content)
        if dev_task and msg.channel != "cli":
            # Store pending task and send for approval
            session.pending_task = dev_task
            self.sessions.save(session)

            # Format the proposal message
            proposal = self._format_task_proposal(dev_task)
            await self._send_immediate(OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=proposal
            ))

            # Don't continue processing, wait for approval
            return None

        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(msg.channel, msg.chat_id)

        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(msg.channel, msg.chat_id)

        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(msg.channel, msg.chat_id)

        # Build initial messages (use get_history for LLM-formatted messages)
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            media=msg.media if msg.media else None,
            channel=msg.channel,
            chat_id=msg.chat_id,
        )

        # Agent loop
        iteration = 0
        final_content = None

        while iteration < self.max_iterations:
            iteration += 1

            # Call LLM
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )

            # Handle tool calls
            if response.has_tool_calls:
                # Add assistant message with tool calls
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)  # Must be JSON string
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )

                # Execute tools
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break

        if final_content is None:
            final_content = "I've completed processing but have no response to give."

        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content
        )

    def _format_task_proposal(self, task: dict[str, Any]) -> str:
        """Format a development task proposal for user approval."""
        lines = [
            "📋 *开发任务方案*",
            "",
            f"**任务分析**: {task.get('analysis', '')}",
            "",
            "**需要的资源**:",
        ]

        for req in task.get('requirements', []):
            lines.append(f"  • {req}")

        lines.append("")
        lines.append(f"**预估成本**: {task.get('estimated_cost', '')}")
        lines.append("")
        lines.append("**实施步骤**:")

        for i, step in enumerate(task.get('steps', []), 1):
            lines.append(f"  {i}. {step}")

        lines.append("")
        lines.append("请确认是否执行: `yes` / `no`")

        return "\n".join(lines)

    async def _handle_task_approval(
        self,
        msg: InboundMessage,
        session: "Session"
    ) -> OutboundMessage | None:
        """
        Handle user's approval response for a pending task.

        Returns approval response and launches background task if approved.
        """
        content = msg.content.strip().lower()

        if content in ("yes", "y", "是", "ok", "confirm"):
            # Approved - launch background task
            pending = session.pending_task
            session.pending_task = None
            self.sessions.save(session)

            # Generate task ID
            task_id = f"TASK-{hash(pending.get('original_request', '')) % 10000:04d}"

            # Launch as background subagent
            task_prompt = f"""Execute this development task:
{pending.get('original_request', '')}

Requirements: {pending.get('requirements', [])}
Steps: {pending.get('steps', [])}

When complete, provide:
1. Summary of what was done
2. Any files created/modified
3. How to use/test the result
4. Any guidelines for future maintenance"""

            # Create a system message for the subagent
            from nanobot.bus.events import InboundMessage
            system_msg = InboundMessage(
                channel="system",
                sender_id=f"task_{task_id}",
                chat_id=f"{msg.channel}:{msg.chat_id}",
                content=task_prompt
            )

            # Publish to inbound queue for processing
            await self.bus.publish_inbound(system_msg)

            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"✅ 任务已批准\n\n任务ID: `{task_id}`\n正在后台执行，完成后会通知你。\n\n你可以发送 `status {task_id}` 查询进度。"
            )

        elif content in ("no", "n", "否", "cancel"):
            # Rejected
            session.pending_task = None
            self.sessions.save(session)

            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="❌ 任务已取消"
            )

        else:
            # Unclear response
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="请回复 `yes` 确认执行，或 `no` 取消任务"
            )
    
    async def _process_system_message(self, msg: InboundMessage) -> OutboundMessage | None:
        """
        Process a system message (e.g., subagent announce).
        
        The chat_id field contains "original_channel:original_chat_id" to route
        the response back to the correct destination.
        """
        logger.info(f"Processing system message from {msg.sender_id}")
        
        # Parse origin from chat_id (format: "channel:chat_id")
        if ":" in msg.chat_id:
            parts = msg.chat_id.split(":", 1)
            origin_channel = parts[0]
            origin_chat_id = parts[1]
        else:
            # Fallback
            origin_channel = "cli"
            origin_chat_id = msg.chat_id
        
        # Use the origin session for context
        session_key = f"{origin_channel}:{origin_chat_id}"
        session = self.sessions.get_or_create(session_key)
        
        # Update tool contexts
        message_tool = self.tools.get("message")
        if isinstance(message_tool, MessageTool):
            message_tool.set_context(origin_channel, origin_chat_id)
        
        spawn_tool = self.tools.get("spawn")
        if isinstance(spawn_tool, SpawnTool):
            spawn_tool.set_context(origin_channel, origin_chat_id)
        
        cron_tool = self.tools.get("cron")
        if isinstance(cron_tool, CronTool):
            cron_tool.set_context(origin_channel, origin_chat_id)
        
        # Build messages with the announce content
        messages = self.context.build_messages(
            history=session.get_history(),
            current_message=msg.content,
            channel=origin_channel,
            chat_id=origin_chat_id,
        )
        
        # Agent loop (limited for announce handling)
        iteration = 0
        final_content = None
        
        while iteration < self.max_iterations:
            iteration += 1
            
            response = await self.provider.chat(
                messages=messages,
                tools=self.tools.get_definitions(),
                model=self.model
            )
            
            if response.has_tool_calls:
                tool_call_dicts = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in response.tool_calls
                ]
                messages = self.context.add_assistant_message(
                    messages, response.content, tool_call_dicts
                )
                
                for tool_call in response.tool_calls:
                    args_str = json.dumps(tool_call.arguments)
                    logger.debug(f"Executing tool: {tool_call.name} with arguments: {args_str}")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                final_content = response.content
                break
        
        if final_content is None:
            final_content = "Background task completed."
        
        # Save to session (mark as system message in history)
        session.add_message("user", f"[System: {msg.sender_id}] {msg.content}")
        session.add_message("assistant", final_content)
        self.sessions.save(session)
        
        return OutboundMessage(
            channel=origin_channel,
            chat_id=origin_chat_id,
            content=final_content
        )
    
    async def process_direct(
        self,
        content: str,
        session_key: str = "cli:direct",
        channel: str = "cli",
        chat_id: str = "direct",
    ) -> str:
        """
        Process a message directly (for CLI or cron usage).
        
        Args:
            content: The message content.
            session_key: Session identifier.
            channel: Source channel (for context).
            chat_id: Source chat ID (for context).
        
        Returns:
            The agent's response.
        """
        msg = InboundMessage(
            channel=channel,
            sender_id="user",
            chat_id=chat_id,
            content=content
        )
        
        response = await self._process_message(msg)
        return response.content if response else ""
