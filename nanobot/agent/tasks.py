"""Task management system for tracking and refining development tasks."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from loguru import logger

# Task categories with their keywords for auto-detection
TASK_CATEGORIES = {
    "app": ["web", "网站", "ui", "界面", "dashboard", "frontend", "后端", "服务", "server", "api"],
    "analyzer": ["分析", "analyze", "检查", "check", "审计", "audit", "report", "报告"],
    "tool": ["工具", "tool", "script", "脚本", "utility", "helper"],
    "fix": ["修复", "fix", "bug", "错误", "error", "问题"],
    "feature": ["功能", "feature", "添加", "add", "新功能", "新的"],
    "data": ["数据", "data", "数据库", "database", "存储", "storage", "爬虫", "crawler", "历史", "history", "记录", "record"],
    "web3": ["钱包", "wallet", "链", "chain", "多链", "multichain", "余额", "balance", "eth", "btc", "nft", "token", "合约", "contract"],
}

# Default category if none matched
DEFAULT_CATEGORY = "task"


@dataclass
class Task:
    """
    A development task that can be refined before execution.

    States:
    - drafting: Initial task creation, collecting requirements
    - refining: User is providing feedback/changes
    - approved: Ready for execution
    - executing: Running in background
    - completed: Done
    - failed: Execution failed
    """

    id: str = ""  # Format: {category}-{number}
    category: str = DEFAULT_CATEGORY
    number: int = 0
    title: str = ""
    description: str = ""
    status: str = "drafting"  # drafting, refining, approved, executing, completed, failed
    requirements: list[str] = field(default_factory=list)
    context: dict[str, Any] = field(default_factory=dict)  # User refinements, Q&A
    proposed_solution: dict[str, Any] = field(default_factory=dict)  # Bot's analysis
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    assigned_to: str | None = None  # Subagent ID when executing

    def add_refinement(self, user_message: str, bot_response: str | None = None, action: str | None = None) -> None:
        """Add a user refinement to the task context."""
        self.context.setdefault("refinements", []).append({
            "timestamp": datetime.now().isoformat(),
            "user": user_message,
            "bot": bot_response,
            "action": action
        })
        self.updated_at = datetime.now()

    def update_requirements(self, new_requirements: list[str]) -> None:
        """Update task requirements."""
        self.requirements = list(set(self.requirements + new_requirements))
        self.updated_at = datetime.now()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "id": self.id,
            "category": self.category,
            "number": self.number,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "requirements": self.requirements,
            "context": self.context,
            "proposed_solution": self.proposed_solution,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "assigned_to": self.assigned_to,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Task":
        """Create from dictionary."""
        task_id = data.get("id", "")

        # Parse category and number from ID (e.g., "app-1")
        category = DEFAULT_CATEGORY
        number = 0
        if task_id and "-" in task_id:
            parts = task_id.split("-", 1)
            if parts[0] in TASK_CATEGORIES or parts[0] == DEFAULT_CATEGORY:
                category = parts[0]
                try:
                    number = int(parts[1])
                except ValueError:
                    pass
        elif data.get("category"):
            category = data["category"]
            number = data.get("number", 0)

        task = cls(
            id=task_id,
            category=category,
            number=number,
            title=data.get("title", ""),
            description=data.get("description", ""),
            status=data.get("status", "drafting"),
            requirements=data.get("requirements", []),
            context=data.get("context", {}),
            proposed_solution=data.get("proposed_solution", {}),
            assigned_to=data.get("assigned_to"),
        )
        if data.get("created_at"):
            task.created_at = datetime.fromisoformat(data["created_at"])
        if data.get("updated_at"):
            task.updated_at = datetime.fromisoformat(data["updated_at"])
        return task

    def format_for_user(self) -> str:
        """Format task details for user display."""
        # Use title as the main display
        title_display = self.title or self.description.split('\n')[0][:50] if self.description else "未命名任务"

        lines = [
            f"{self._status_emoji()} **{self.id}** - *{title_display}*",
            "",
        ]

        if self.description:
            # Show description but truncate if too long
            desc = self.description
            if len(desc) > 200:
                desc = desc[:200] + "..."
            lines.append(f"{desc}")
            lines.append("")

        if self.requirements:
            lines.append("**需求**:")
            for req in self.requirements:
                lines.append(f"  • {req}")
            lines.append("")

        if self.proposed_solution:
            sol = self.proposed_solution
            if sol.get("analysis"):
                lines.append(f"**方案**: {sol['analysis']}")
                lines.append("")
            if sol.get("steps"):
                lines.append("**步骤**:")
                for i, step in enumerate(sol.get("steps", []), 1):
                    lines.append(f"  {i}. {step}")
                lines.append("")

        refinements = self.context.get("refinements", [])
        if refinements:
            lines.append(f"**迭代** ({len(refinements)}次):")
            lines.append("")

        return "\n".join(lines)

    def _status_emoji(self) -> str:
        """Get emoji for task status."""
        emojis = {
            "drafting": "📝",
            "refining": "🔧",
            "approved": "✅",
            "executing": "🔄",
            "completed": "✨",
            "failed": "❌",
        }
        return emojis.get(self.status, "📋")


class TaskManager:
    """Manages tasks within a session."""

    def __init__(self, session_key: str):
        self.session_key = session_key
        self._tasks: dict[str, Task] = {}
        self._counters: dict[str, int] = {}  # Track next number per category

    def _detect_category(self, description: str) -> str:
        """Detect task category from description."""
        desc_lower = description.lower()

        # Check each category's keywords
        for category, keywords in TASK_CATEGORIES.items():
            if any(keyword in desc_lower for keyword in keywords):
                return category

        return DEFAULT_CATEGORY

    def _get_next_number(self, category: str) -> int:
        """Get next number for a category."""
        if category not in self._counters:
            # Find the highest existing number for this category
            max_num = 0
            for task in self._tasks.values():
                if task.category == category and task.number > max_num:
                    max_num = task.number
            self._counters[category] = max_num
        self._counters[category] += 1
        return self._counters[category]

    def create_task(
        self,
        title: str,
        description: str,
        proposed_solution: dict[str, Any] | None = None,
        category: str | None = None,
    ) -> Task:
        """Create a new task."""
        # Detect or use provided category
        if not category:
            category = self._detect_category(description)

        # Generate ID
        number = self._get_next_number(category)
        task_id = f"{category}-{number}"

        task = Task(
            id=task_id,
            category=category,
            number=number,
            title=title,
            description=description,
            proposed_solution=proposed_solution or {},
        )
        self._tasks[task.id] = task
        logger.info(f"Created task {task.id}: {title}")
        return task

    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        return self._tasks.get(task_id)

    def get_active_task(self) -> Task | None:
        """Get the currently active task (drafting or refining)."""
        for task in self._tasks.values():
            if task.status in ("drafting", "refining"):
                return task
        return None

    def update_task(
        self,
        task_id: str,
        title: str | None = None,
        description: str | None = None,
        requirements: list[str] | None = None,
    ) -> Task | None:
        """Update an existing task."""
        task = self._tasks.get(task_id)
        if not task:
            return None

        if title is not None:
            task.title = title
        if description is not None:
            task.description = description
        if requirements is not None:
            task.update_requirements(requirements)

        task.updated_at = datetime.now()
        return task

    def add_refinement(self, task_id: str, user_message: str, bot_response: str | None = None, action: str | None = None) -> Task | None:
        """Add a user refinement to a task."""
        task = self._tasks.get(task_id)
        if not task:
            return None

        # Move to refining state if in drafting
        if task.status == "drafting":
            task.status = "refining"

        task.add_refinement(user_message, bot_response, action)
        return task

    def approve_task(self, task_id: str) -> Task | None:
        """Approve a task for execution."""
        task = self._tasks.get(task_id)
        if not task:
            return None

        task.status = "approved"
        task.updated_at = datetime.now()
        return task

    def set_task_status(self, task_id: str, status: str) -> Task | None:
        """Set task status."""
        task = self._tasks.get(task_id)
        if not task:
            return None

        task.status = status
        task.updated_at = datetime.now()
        return task

    def delete_task(self, task_id: str) -> bool:
        """Delete a task by ID."""
        if task_id in self._tasks:
            del self._tasks[task_id]
            logger.info(f"Deleted task {task_id}")
            return True
        return False

    def list_tasks(self, status: str | None = None) -> list[Task]:
        """List all tasks, optionally filtered by status."""
        tasks = list(self._tasks.values())
        if status:
            tasks = [t for t in tasks if t.status == status]
        return sorted(tasks, key=lambda t: t.updated_at, reverse=True)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "session_key": self.session_key,
            "tasks": {tid: t.to_dict() for tid, t in self._tasks.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskManager":
        """Create from dictionary."""
        manager = cls(data.get("session_key", ""))
        for tid, tdata in data.get("tasks", {}).items():
            task = Task.from_dict(tdata)
            manager._tasks[tid] = task
            # Restore counters
            if task.category not in manager._counters:
                manager._counters[task.category] = 0
            if task.number >= manager._counters[task.category]:
                manager._counters[task.category] = task.number
        return manager
