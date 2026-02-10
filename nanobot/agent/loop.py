"""Agent loop: the core processing engine."""

import asyncio
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

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
from nanobot.agent.tasks import TaskManager, Task
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
        restrict_to_workspace: bool = False,
        session_manager: SessionManager | None = None,
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
        self.restrict_to_workspace = restrict_to_workspace
        self._channel_manager = None  # Will be set by ChannelManager

        self.context = ContextBuilder(workspace)
        self.sessions = session_manager or SessionManager(workspace)
        self.tools = ToolRegistry()
        self.subagents = SubagentManager(
            provider=provider,
            workspace=workspace,
            bus=bus,
            model=self.model,
            brave_api_key=brave_api_key,
            exec_config=self.exec_config,
            restrict_to_workspace=restrict_to_workspace,
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

    def _classify_message(self, content: str) -> dict[str, Any]:
        """
        Classify the message type to determine acknowledgment strategy.

        Returns:
            dict with:
            - needs_ack: bool - whether to send acknowledgment
            - type: str - message category
            - ack_message: str | None - custom ack message
            - expected_time: str - expected response time hint
        """
        import re
        content_lower = content.lower().strip()
        content_stripped = content.strip()

        # 1. Greetings - NO ACK, fast response
        greetings = [
            "hello", "hi", "hey", "嗨", "你好", "您好", "哈喽",
            "morning", "afternoon", "evening", "早上好", "下午好", "晚上好",
            "thanks", "thank you", "谢谢", "感谢", "thx", "bye", "再见",
            "ok", "okay", "好的", "行", "是", "yes", "no", "否"
        ]
        if content_stripped in greetings or content_lower in greetings:
            return {"needs_ack": False, "type": "greeting"}

        # 2. Simple questions - NO ACK, fast LLM response
        # Single short questions without complex requirements
        simple_patterns = [
            r"^(what|how|why|when|where|who|which|是|什么|怎么|为什么|何时|何地|谁)\s",
            r"^(can|could|will|would|do|does|did|是|能不能|会|要)\s",
            r"^(tell|say|explain|describe|讲|说|解释|描述)\s",
        ]
        for pattern in simple_patterns:
            if re.match(pattern, content_lower) and len(content_stripped) < 100:
                # Check if it's NOT asking for something complex
                complex_indicators = ["code", "代码", "analyze", "分析", "search", "搜索",
                                     "find", "找", "write", "写", "create", "创建", "build", "build"]
                if not any(indicator in content_lower for indicator in complex_indicators):
                    return {"needs_ack": False, "type": "simple_question"}

        # 3. Code/Development tasks - NEED ACK, takes time
        dev_keywords = ["写", "write", "create", "创建", "build", "implement", "实现",
                       "code", "代码", "function", "函数", "class", "类", "api", "endpoint",
                       "refactor", "重构", "fix", "修复", "bug", "debug", "调试"]
        if any(keyword in content_lower for keyword in dev_keywords):
            return {
                "needs_ack": True,
                "type": "dev_task",
                "ack_message": "💻 收到开发任务，正在分析需求...",
                "expected_time": "30s-2m"
            }

        # 4. Search/Research tasks - NEED ACK, external API calls
        search_keywords = ["search", "搜索", "find", "找", "look up", "查询",
                          "research", "research", "investigate", "调查", "google"]
        if any(keyword in content_lower for keyword in search_keywords):
            return {
                "needs_ack": True,
                "type": "search",
                "ack_message": "🔎 正在搜索相关信息...",
                "expected_time": "10-30s"
            }

        # 5. Analysis tasks - NEED ACK, multiple tool calls
        analysis_keywords = ["analyze", "分析", "check", "检查", "review", "review",
                           "audit", "审计", "compare", "比较", "evaluate", "评估"]
        if any(keyword in content_lower for keyword in analysis_keywords):
            return {
                "needs_ack": True,
                "type": "analysis",
                "ack_message": "🔍 收到分析请求，正在处理...",
                "expected_time": "15-60s"
            }

        # 6. File operations - NEED ACK
        file_keywords = ["read", "读", "write", "写", "edit", "编辑",
                        "delete", "删除", "move", "移动", "copy", "复制", "file", "文件"]
        if any(keyword in content_lower for keyword in file_keywords):
            return {
                "needs_ack": True,
                "type": "file_ops",
                "ack_message": "📁 正在处理文件操作...",
                "expected_time": "5-15s"
            }

        # 7. Long messages (>150 chars) - NEED ACK, likely complex
        if len(content_stripped) > 150:
            return {
                "needs_ack": True,
                "type": "complex",
                "ack_message": "🤔 收到复杂请求，正在思考...",
                "expected_time": "20-60s"
            }

        # 8. Default: short messages - NO ACK
        return {"needs_ack": False, "type": "default"}

    async def _send_acknowledgment(self, msg: InboundMessage) -> None:
        """Send an immediate acknowledgment message based on message classification."""
        # Only for Slack and Telegram (not CLI)
        if msg.channel not in ("slack", "telegram"):
            return

        classification = self._classify_message(msg.content)

        if not classification["needs_ack"]:
            return

        ack = classification.get("ack_message", "👍 收到！")

        await self._send_immediate(OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=ack,
            metadata=msg.metadata  # Include thread_ts for Slack
        ))

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
        # File tools (restrict to workspace if configured)
        allowed_dir = self.workspace if self.restrict_to_workspace else None
        self.tools.register(ReadFileTool(allowed_dir=allowed_dir))
        self.tools.register(WriteFileTool(allowed_dir=allowed_dir))
        self.tools.register(EditFileTool(allowed_dir=allowed_dir))
        self.tools.register(ListDirTool(allowed_dir=allowed_dir))
        
        # Shell tool
        self.tools.register(ExecTool(
            working_dir=str(self.workspace),
            timeout=self.exec_config.timeout,
            restrict_to_workspace=self.restrict_to_workspace,
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
            llm_content = response.content or "{}"

            # Try to extract JSON from response
            result = None
            try:
                result = json.loads(llm_content)
            except json.JSONDecodeError:
                # Try to find JSON in the response
                import re
                json_match = re.search(r'\{[^}]*"is_dev_task"[^}]*\}', llm_content, re.DOTALL)
                if json_match:
                    try:
                        result = json.loads(json_match.group(0))
                    except json.JSONDecodeError:
                        pass

            # If still no valid JSON, create a default dev task
            if not result:
                logger.warning(f"Could not parse JSON from LLM, creating default task. Response: {llm_content[:100]}")
                result = {"is_dev_task": True}

            if result.get("is_dev_task"):
                return {
                    "type": "dev_task",
                    "original_request": content,  # User's original request
                    "analysis": result.get("analysis", "Development task based on user request"),
                    "requirements": result.get("requirements", []),
                    "estimated_cost": result.get("estimated_cost", "30-60 minutes"),
                    "steps": result.get("steps", ["Analyze requirements", "Implement solution", "Test and deploy"]),
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

        preview = msg.content[:80] + "..." if len(msg.content) > 80 else msg.content
        logger.info(f"Processing message from {msg.channel}:{msg.sender_id}: {preview}")

        # Get or create session (needed for task check)
        session = self.sessions.get_or_create(msg.session_key)

        # Check for /task commands FIRST (even without active task)
        content_stripped = msg.content.strip().lower()
        if content_stripped.startswith("/task") and msg.channel != "cli":
            task_response = await self._handle_task_command(msg, session, None)
            if task_response:
                return task_response

        # Check for active task refinement (before ack)
        # This allows iterative development on tasks
        if session.active_task_id and msg.channel != "cli":
            task_response = await self._handle_task_refinement(msg, session)
            if task_response:
                # If task_response is not None, it means the task system handled it
                return task_response
            # If None, fall through to normal processing

        # Send acknowledgment immediately for Slack/Telegram
        await self._send_acknowledgment(msg)

        # Check if there's a pending task awaiting approval (legacy flow)
        if session.pending_task and not session.active_task_id:
            return await self._handle_task_approval(msg, session)

        # Check if message references an existing task (by title or exact description match)
        task_manager = session.get_task_manager()
        existing_task = None
        content_stripped = msg.content.strip()
        content_lower = content_stripped.lower()

        # Check if message starts with a task ID (e.g., "app-1 fix the bug")
        # Pattern: task-id followed by space and more content
        task_id_match = re.match(r'^([a-z]+-\d+)\s+(.+)', content_stripped, re.IGNORECASE)
        if task_id_match:
            referenced_task_id = task_id_match.group(1).lower()
            refinement_content = task_id_match.group(2)
            referenced_task = task_manager.get_task(referenced_task_id)
            if referenced_task:
                # User is referencing an existing task - add as refinement
                logger.info(f"Found task by reference '{referenced_task_id}': {referenced_task_id}")
                referenced_task.add_refinement(refinement_content, action="modified")
                referenced_task.status = "refining"
                session.active_task_id = referenced_task.id
                session.save_tasks(task_manager)
                self.sessions.save(session)

                # Show the updated task with the new refinement
                lines = [
                    f"📝 已添加到 `{referenced_task.id}` - *{referenced_task.title}*",
                    "",
                    "**新需求:**",
                    f"  {refinement_content}",
                    "",
                    f"{referenced_task.format_for_user()}",
                    "",
                    "---",
                    "回复 `yes` 执行，或继续补充需求。",
                ]
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="\n".join(lines),
                    metadata=msg.metadata,
                )

        # Sort by created_at to find the OLDEST matching task (not most recent)
        all_tasks = sorted(task_manager._tasks.values(), key=lambda t: t.created_at)

        for task in all_tasks:
            # Check exact title match or description match
            if (task.title and task.title.lower() == content_lower) or \
               (task.description and task.description.lower() == content_lower):
                existing_task = task
                logger.info(f"Found matching task: {task.id} title={task.title}")
                break

        if existing_task and msg.channel != "cli":
            logger.info(f"Message matches existing task {existing_task.id}, showing it")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"ℹ️ 这个任务已存在:\n\n{existing_task.format_for_user()}\n\n---\n回复 `yes` 继续执行此任务，或发送新需求创建新任务。",
                metadata=msg.metadata,
            )

        # Check if this is a development task that needs approval
        # Skip if we already have an active task in refinement
        dev_task = await self._analyze_development_task(msg.content)
        if dev_task and msg.channel != "cli" and not session.active_task_id:
            # Use new task system
            return await self._create_task(msg, session, dev_task)

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
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
                    result = await self.tools.execute(tool_call.name, tool_call.arguments)
                    messages = self.context.add_tool_result(
                        messages, tool_call.id, tool_call.name, result
                    )
            else:
                # No tool calls, we're done
                final_content = response.content
                break

        if final_content is None:
            # Tools were executed but no final content - ask for summary
            logger.info("No final content after tool execution, requesting summary...")
            messages.append({
                "role": "user",
                "content": "请基于以上工具执行结果，用简洁的语言总结你完成的任务。"
            })
            summary_response = await self.provider.chat(
                messages=messages,
                tools=None,
                model=self.model,
                max_tokens=1000
            )
            final_content = summary_response.content or "✅ 任务已完成"

        # Log response preview
        preview = final_content[:120] + "..." if len(final_content) > 120 else final_content
        logger.info(f"Response to {msg.channel}:{msg.sender_id}: {preview}")
        # Save to session
        session.add_message("user", msg.content)
        session.add_message("assistant", final_content)
        self.sessions.save(session)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=final_content,
            metadata=msg.metadata  # Include thread_ts for Slack replies
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

    def _extract_task_title(self, content: str) -> str:
        """Extract a short title from task description."""
        # Clean common prefixes
        prefixes = ["我需要", "我想要", "帮我", "请", "can you", "i need", "please"]
        for prefix in prefixes:
            if content.lower().startswith(prefix):
                content = content[len(prefix):].strip()

        lines = content.strip().split("\n")
        first_line = lines[0].strip()

        # Truncate if too long
        if len(first_line) > 40:
            # Try to end at a word boundary
            truncated = first_line[:40]
            last_space = truncated.rfind(" ")
            if last_space > 20:
                truncated = truncated[:last_space]
            return truncated + "..."

        return first_line

    async def _create_task(
        self,
        msg: InboundMessage,
        session: "Session",
        dev_task: dict[str, Any],
    ) -> OutboundMessage | None:
        """
        Create a new task from a development request.

        Creates task in drafting state and shows it to user for refinement.
        """
        task_manager = session.get_task_manager()

        title = self._extract_task_title(dev_task.get("original_request", ""))
        logger.info(f"Creating task: title={title}, description={dev_task.get('original_request', '')[:50]}")

        task = task_manager.create_task(
            title=title,
            description=dev_task.get("original_request", ""),
            proposed_solution=dev_task,
        )

        logger.info(f"Task created: id={task.id}, category={task.category}, number={task.number}")

        # Extract requirements from analysis
        if dev_task.get("requirements"):
            task.update_requirements(dev_task["requirements"])

        # Set as active task
        session.active_task_id = task.id
        session.save_tasks(task_manager)
        self.sessions.save(session)

        logger.info(f"Task saved: active_task_id={session.active_task_id}, tasks_data_keys={list(session.tasks_data.get('tasks', {}).keys()) if session.tasks_data else None}")

        # Show task to user
        task.status = "refining"  # Allow refinement immediately
        summary = task.format_for_user()

        lines = [
            f"✅ 任务已创建: `{task.id}`",
            "",
            summary,
            "",
            "---",
            "💡 你可以:",
            "  • 补充或修改需求 (直接发送)",
            "  • 提问相关问题",
            "  • 回复 `yes` 批准执行",
            "  • 回复 `cancel` 取消任务",
            "",
        ]

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content="\n".join(lines),
            metadata=msg.metadata,
        )

    async def _handle_task_refinement(
        self,
        msg: InboundMessage,
        session: "Session",
    ) -> OutboundMessage | None:
        """
        Handle user input for an active task (refinement/approval).

        Returns:
            Response message, or None to continue normal processing.
        """
        content = msg.content.strip().lower()
        task_manager = session.get_task_manager()
        task = task_manager.get_task(session.active_task_id) if session.active_task_id else None

        if not task:
            # No active task, clear the reference
            session.active_task_id = None
            self.sessions.save(session)
            return None

        # Check for approval
        if content in ("yes", "y", "是", "ok", "confirm", "approve", "批准"):
            task_manager.approve_task(task.id)
            session.active_task_id = None
            session.save_tasks(task_manager)
            self.sessions.save(session)

            # Launch as background subagent
            return await self._execute_task(msg, task)

        # Check for cancellation
        if content in ("no", "n", "否", "cancel", "取消"):
            task_manager.set_task_status(task.id, "cancelled")
            session.active_task_id = None
            session.save_tasks(task_manager)
            self.sessions.save(session)

            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="❌ 任务已取消",
                metadata=msg.metadata,
            )

        # Check for task commands
        if content.startswith("/task"):
            return await self._handle_task_command(msg, session, task_manager, task, content)

        # Otherwise, treat as refinement - ask LLM to incorporate feedback
        return await self._process_refinement(msg, session, task_manager, task)

    async def _handle_task_command(
        self,
        msg: InboundMessage,
        session: "Session",
        task: Task | None,
        content: str | None = None,
    ) -> OutboundMessage | None:
        """Handle task-related commands."""
        content = content or msg.content.strip().lower()
        parts = content.split()
        cmd = parts[1] if len(parts) > 1 else ""
        arg = parts[2] if len(parts) > 2 else ""  # Task ID argument

        logger.info(f"_handle_task_command: cmd={cmd}, arg={arg}, content={content}")

        task_manager = session.get_task_manager()
        all_tasks = task_manager.list_tasks()
        logger.info(f"TaskManager has {len(all_tasks)} tasks: {[t.id for t in all_tasks]}")

        if cmd in ("show", "status"):
            # If task ID provided, try to get that specific task
            if arg:
                task = task_manager.get_task(arg)
                logger.info(f"Looking for task '{arg}': found={task is not None}")
            # Otherwise use active task
            if not task:
                task = task_manager.get_task(session.active_task_id) if session.active_task_id else None
                logger.info(f"Using active task '{session.active_task_id}': found={task is not None}")
            if not task:
                logger.warning(f"Task not found: arg={arg}, active={session.active_task_id}")
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"📋 任务 `{arg}` 不存在\n\n发送一个功能请求来创建新任务" if arg else "📋 没有活动任务\n\n发送一个功能请求来创建新任务",
                    metadata=msg.metadata,
                )

            # Send acknowledgment if task is executing (will take time to get status)
            if task.status == "executing" and msg.channel != "cli":
                await self._send_immediate(OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"🔍 正在查询 `{task.id}` 的执行状态...",
                    metadata=msg.metadata,
                ))

            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=task.format_for_user(),
                metadata=msg.metadata,
            )

        if cmd == "list":
            all_tasks = task_manager.list_tasks()
            if not all_tasks:
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="📋 暂无任务\n\n发送一个功能请求来创建新任务",
                    metadata=msg.metadata,
                )
            lines = ["📋 **任务列表**\n"]
            for i, t in enumerate(all_tasks, 1):
                title = t.title or (t.description.split('\n')[0][:35] if t.description else "未命名")
                marker = " ← *进行中*" if t.id == session.active_task_id else ""
                lines.append(f"{i}. {t._status_emoji()} {title}{marker}")
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="\n".join(lines),
                metadata=msg.metadata,
            )

        if cmd == "clear":
            if session.active_task_id:
                session.active_task_id = None
                self.sessions.save(session)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content="✅ 已清除当前活动任务",
                    metadata=msg.metadata,
                )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="没有活动任务需要清除",
                metadata=msg.metadata,
            )

        if cmd == "delete" and arg:
            # Delete a specific task
            if task_manager.delete_task(arg):
                session.save_tasks(task_manager)
                if session.active_task_id == arg:
                    session.active_task_id = None
                self.sessions.save(session)
                return OutboundMessage(
                    channel=msg.channel,
                    chat_id=msg.chat_id,
                    content=f"✅ 已删除任务 `{arg}`",
                    metadata=msg.metadata,
                )
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content=f"❌ 任务 `{arg}` 不存在",
                metadata=msg.metadata,
            )

        # Unknown command or no subcommand
        if not cmd:
            # Show brief help
            all_tasks = task_manager.list_tasks()
            if all_tasks:
                lines = ["📋 **任务**\n", ""]
                for t in all_tasks[:3]:  # Show last 3 tasks
                    title = t.title or (t.description.split('\n')[0][:30] if t.description else "未命名")
                    marker = " ← *进行中*" if t.id == session.active_task_id else ""
                    lines.append(f"{t._status_emoji()} {title}{marker}")
                lines.append("\n可用: /task show, /task list, /task clear")
            else:
                lines = ["📋 暂无任务", "", "发送功能请求来创建新任务"]
            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="\n".join(lines),
                metadata=msg.metadata,
            )

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content="可用命令: /task show, /task list, /task clear",
            metadata=msg.metadata,
        )

    async def _process_refinement(
        self,
        msg: InboundMessage,
        session: "Session",
        task_manager: TaskManager,
        task: Task,
    ) -> OutboundMessage | None:
        """
        Process user refinement and update the task.

        Uses LLM to understand if this is:
        1. A new requirement to add
        2. A question about the task
        3. A modification to the plan
        """
        # Build refinement analysis prompt
        refinement_prompt = [
            {
                "role": "system",
                "content": f"""You are helping refine a development task.

Current Task:
ID: {task.id}
Title: {task.title}
Description: {task.description}
Requirements: {', '.join(task.requirements) if task.requirements else 'None'}

Proposed Solution:
{json.dumps(task.proposed_solution, ensure_ascii=False, indent=2)}

Previous Refinements: {len(task.context.get('refinements', []))}

Analyze the user's new input and respond with JSON:
{{
    "is_approval": true/false,
    "is_question": true/false,
    "is_requirement": true/false,
    "new_requirements": ["list of new requirements if any"],
    "updates": "description of what should be updated",
    "response": "your response to the user"
}}

Rules:
- If user says yes/confirm/批准, set is_approval=true
- If user asks a question, set is_question=true and provide response
- If user adds/modifies requirements, extract them as new_requirements
- Always provide a helpful response"""
            },
            {"role": "user", "content": msg.content},
        ]

        try:
            response = await self.provider.chat(
                messages=refinement_prompt,
                tools=None,
                model=self.model,
                max_tokens=800,
                temperature=0.3,
            )

            result = json.loads(response.content or "{}")

            # Check if this is actually an approval
            if result.get("is_approval"):
                return await self._handle_task_refinement(
                    InboundMessage(
                        channel=msg.channel,
                        sender_id=msg.sender_id,
                        chat_id=msg.chat_id,
                        content="yes",
                        metadata=msg.metadata,
                    ),
                    session,
                )

            # Add refinement to task
            bot_response = result.get("response", "")
            task_manager.add_refinement(task.id, msg.content, bot_response)

            # Update requirements if provided
            if result.get("new_requirements"):
                task.update_requirements(result.get("new_requirements", []))

            # Update description if there are updates
            if result.get("updates"):
                task.description = f"{task.description}\n\n更新: {result.get('updates')}"

            session.save_tasks(task_manager)
            self.sessions.save(session)

            # Format response with task status
            lines = [
                bot_response or "✅ 已记录你的反馈",
                "",
            ]

            # Show updated requirements if changed
            if result.get("new_requirements"):
                lines.append("**更新的需求**:")
                for req in result.get("new_requirements", []):
                    lines.append(f"  • {req}")
                lines.append("")

            # Show task summary
            lines.append("---")
            lines.append(f"📋 当前任务: `{task.id}`")
            lines.append(f"状态: {task._status_emoji()} `{task.status}`")
            lines.append(f"需求数: {len(task.requirements)}")
            lines.append("")
            lines.append("回复 `yes` 批准执行，或继续补充需求")

            return OutboundMessage(
                channel=msg.channel,
                chat_id=msg.chat_id,
                content="\n".join(lines),
                metadata=msg.metadata,
            )

        except Exception as e:
            logger.warning(f"Failed to process refinement: {e}")
            # Fallback: just acknowledge and let normal processing continue
            task_manager.add_refinement(task.id, msg.content)
            session.save_tasks(task_manager)
            self.sessions.save(session)
            return None

    async def _execute_task(
        self,
        msg: InboundMessage,
        task: Task,
    ) -> OutboundMessage:
        """Execute an approved task as a background subagent."""
        task_id = f"TASK-{task.id[:4].upper()}"

        # Build task prompt with all context
        refinements = task.context.get("refinements", [])
        refinement_text = ""
        if refinements:
            refinement_text = "\n\n用户需求迭代:\n"
            for i, ref in enumerate(refinements, 1):
                refinement_text += f"{i}. {ref['user']}\n"

        task_prompt = f"""Execute this development task:

任务ID: {task_id}
标题: {task.title}

描述:
{task.description}

需求:
{chr(10).join(f'  • {r}' for r in task.requirements) if task.requirements else '  无特定需求'}{refinement_text}

方案:
{json.dumps(task.proposed_solution, ensure_ascii=False, indent=2)}

When complete, provide:
1. 完成内容摘要
2. 创建/修改的文件列表
3. 如何使用/测试结果
4. 后续维护建议"""

        # Create system message for subagent
        system_msg = InboundMessage(
            channel="system",
            sender_id=f"task_{task_id}",
            chat_id=f"{msg.channel}:{msg.chat_id}",
            content=task_prompt,
        )

        # Mark task as executing
        task.status = "executing"
        # Will be saved when session is saved

        # Publish to inbound queue
        await self.bus.publish_inbound(system_msg)

        return OutboundMessage(
            channel=msg.channel,
            chat_id=msg.chat_id,
            content=f"✅ 任务已批准\n\n任务ID: `{task_id}`\n正在后台执行...\n\n发送 `status {task_id}` 查询进度",
            metadata=msg.metadata,
        )

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
                    args_str = json.dumps(tool_call.arguments, ensure_ascii=False)
                    logger.info(f"Tool call: {tool_call.name}({args_str[:200]})")
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
