"""Skill discovery and listing system."""

import os
import json
from pathlib import Path
from typing import Any
from dataclasses import dataclass
from loguru import logger


@dataclass
class SkillInfo:
    """Information about a skill."""
    name: str
    description: str
    emoji: str = "📦"
    category: str = "general"
    requires_env: list[str] | None = None
    requires_bins: list[str] | None = None
    always_loaded: bool = False
    path: str | None = None

    @property
    def is_available(self) -> bool:
        """Check if skill requirements are met."""
        if self.requires_env:
            for env_var in self.requires_env:
                if not os.environ.get(env_var):
                    return False
        if self.requires_bins:
            import shutil
            for bin_name in self.requires_bins:
                if not shutil.which(bin_name):
                    return False
        return True

    def format_inline(self) -> str:
        """Format skill for inline display."""
        status = "✅" if self.is_available else "🔒"
        req = ""
        if self.requires_env and not self.is_available:
            req = f" (需: {', '.join(self.requires_env)})"
        return f"{status} {self.emoji} **{self.name}** - {self.description}{req}"

    def format_detail(self) -> str:
        """Format skill for detailed display."""
        lines = [
            f"{self.emoji} **{self.name}**",
            f"   {self.description}",
        ]

        # Availability status
        if self.is_available:
            lines.append("   状态: ✅ 可用")
        else:
            lines.append("   状态: 🔒 缺少依赖")
            if self.requires_env:
                lines.append(f"   需要: {', '.join(self.requires_env)}")
            if self.requires_bins:
                lines.append(f"   需要: {', '.join(self.requires_bins)}")

        if self.always_loaded:
            lines.append("   自动加载: 是")

        return "\n".join(lines)


class SkillDiscovery:
    """Discover and list available skills."""

    def __init__(self, skills_dir: str | Path | None = None):
        if skills_dir is None:
            # Default to nanobot/skills
            import inspect
            this_file = Path(__file__)
            skills_dir = this_file.parent
        self.skills_dir = Path(skills_dir)
        self._cache: dict[str, SkillInfo] = {}

    def discover(self, force_refresh: bool = False) -> dict[str, SkillInfo]:
        """Discover all skills in the skills directory."""
        if self._cache and not force_refresh:
            return self._cache

        self._cache = {}

        if not self.skills_dir.exists():
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return self._cache

        for skill_path in self.skills_dir.iterdir():
            if not skill_path.is_dir() or skill_path.name.startswith("."):
                continue

            skill_md = skill_path / "SKILL.md"
            if not skill_md.exists():
                continue

            info = self._parse_skill_md(skill_path, skill_md)
            if info:
                self._cache[info.name] = info

        logger.info(f"Discovered {len(self._cache)} skills")
        return self._cache

    def _parse_skill_md(self, skill_path: Path, md_file: Path) -> SkillInfo | None:
        """Parse a SKILL.md file and extract metadata."""
        try:
            with open(md_file) as f:
                content = f.read()

            # Extract frontmatter (between ---)
            lines = content.split("\n")
            frontmatter_lines = []
            in_frontmatter = False

            for line in lines:
                if line.strip() == "---":
                    if not in_frontmatter:
                        in_frontmatter = True
                    else:
                        break
                elif in_frontmatter:
                    frontmatter_lines.append(line)

            frontmatter = "\n".join(frontmatter_lines)

            # Parse YAML-like frontmatter
            import re
            name_match = re.search(r'name:\s*["\']?([^"\'\n]+)["\']?', frontmatter)
            # Description can be quoted or unquoted, capture until end of line or next field
            desc_match = re.search(r'description:\s*["\']?([^"\'\n]+(?:[^"\n"[^\']+)*)["\']?', frontmatter)
            # For metadata, find the full JSON object (already includes braces)
            metadata_match = re.search(r'metadata:\s*(\{.*\})', frontmatter, re.DOTALL)

            name = name_match.group(1) if name_match else skill_path.name
            description = desc_match.group(1) if desc_match else "No description"

            # Parse metadata
            emoji = "📦"
            category = "general"
            requires_env = None
            requires_bins = None
            always_loaded = False

            if metadata_match:
                metadata_str = metadata_match.group(1)  # Already includes braces
                try:
                    metadata = json.loads(metadata_str.replace("'", '"'))
                    nanobot_meta = metadata.get("nanobot", {})
                    emoji = nanobot_meta.get("emoji", emoji)
                    always_loaded = nanobot_meta.get("always", False)
                    requires = nanobot_meta.get("requires", {})
                    requires_env = requires.get("env", [])
                    requires_bins = requires.get("bins", [])
                except json.JSONDecodeError:
                    pass

            # Determine category
            if skill_path.name in ["web3-core", "wallet-tracker", "token-analyzer",
                                   "whale-monitor", "defi-analyzer"]:
                category = "web3"
            elif skill_path.name in ["github", "weather", "summarize", "tmux", "cron"]:
                category = "tools"
            elif skill_path.name in ["skill-creator", "skill-researcher"]:
                category = "meta"

            return SkillInfo(
                name=name,
                description=description,
                emoji=emoji,
                category=category,
                requires_env=requires_env,
                requires_bins=requires_bins,
                always_loaded=always_loaded,
                path=str(skill_path)
            )

        except Exception as e:
            logger.warning(f"Failed to parse skill {md_file}: {e}")
            return None

    def get_all(self) -> list[SkillInfo]:
        """Get all skills as a list."""
        skills = self.discover()
        return list(skills.values())

    def get_by_category(self, category: str) -> list[SkillInfo]:
        """Get skills by category."""
        return [s for s in self.get_all() if s.category == category]

    def get_available(self) -> list[SkillInfo]:
        """Get only available skills (requirements met)."""
        return [s for s in self.get_all() if s.is_available]

    def get_skill(self, name: str) -> SkillInfo | None:
        """Get a specific skill by name."""
        skills = self.discover()
        return skills.get(name)

    def format_list(self, category: str | None = None) -> str:
        """Format skills list for display."""
        if category:
            skills = self.get_by_category(category)
            title = f"📦 可用 Skills - {category.title()}"
        else:
            skills = self.get_all()
            title = "📦 可用 Skills"

        lines = [title, ""]

        # Group by category
        by_category: dict[str, list[SkillInfo]] = {}
        for skill in skills:
            if skill.category not in by_category:
                by_category[skill.category] = []
            by_category[skill.category].append(skill)

        # Sort categories: web3, tools, meta, general
        category_order = ["web3", "tools", "meta", "general"]
        for cat in category_order:
            if cat not in by_category:
                continue
            cat_title = {
                "web3": "🔗 Web3",
                "tools": "🛠️ 工具",
                "meta": "📋 Meta",
                "general": "📦 通用"
            }.get(cat, cat.title())

            lines.append(f"\n**{cat_title}**")
            for skill in by_category[cat]:
                lines.append(f"  {skill.format_inline()}")

        lines.append("\n使用方式: 直接发送任务描述，相关 skill 会自动加载")
        lines.append("或使用 `/use <skill-name>` 明确指定使用某个 skill")

        return "\n".join(lines)

    def format_skill_detail(self, name: str) -> str | None:
        """Format detailed info for a specific skill."""
        skill = self.get_skill(name)
        if not skill:
            return None
        return skill.format_detail()


# Global instance
_discovery_instance: SkillDiscovery | None = None


def get_discovery() -> SkillDiscovery:
    """Get the global skill discovery instance."""
    global _discovery_instance
    if _discovery_instance is None:
        _discovery_instance = SkillDiscovery()
    return _discovery_instance
