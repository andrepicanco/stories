"""Monta o agente para uma execução: persona + skills + memória + tools permitidas."""
import os
from dataclasses import dataclass
from pathlib import Path

from .base import Tool, ToolContext
from .memory import Memory
from .prompts import build_system_prompt
from .registry import count_by_group, discover_tools, filter_tools
from .skills import SkillRegistry

ROOT = Path(__file__).resolve().parent.parent
MEMORY_PATH = Path(os.environ.get("STORIES_MEMORY_PATH") or ROOT / "storage" / "memory.json")


def resolve_dir(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


@dataclass
class Agent:
    system_prompt: str
    tools: list[Tool]          # já filtradas pela allowlist
    warnings: list[str]
    max_steps: int
    max_tool_output: int
    memory: Memory


def build_agent(settings: dict, enabled_groups: list[str], memory_path: Path = MEMORY_PATH) -> Agent:
    cfg = settings["agent"]
    ctx = ToolContext(settings=settings, root=ROOT, max_tool_output=cfg["max_tool_output"])

    skills = SkillRegistry(resolve_dir(cfg["skills_dir"]))
    memory = Memory(memory_path)

    all_tools, tool_errors = discover_tools(resolve_dir(cfg["tools_dir"]), ctx)
    all_tools.append(skills.tool())
    tools = filter_tools(all_tools, enabled_groups)

    prompt = build_system_prompt(
        persona=cfg.get("system_prompt", ""),
        skills_block=skills.index_block(),
        memory_block=memory.prompt_block(),
        enabled_groups=enabled_groups,
        tools_by_group=count_by_group(tools),
        notion_root=settings["notion"].get("root_page", ""),
        wiki_root=settings["azure"].get("wiki_url", ""),
    )
    return Agent(
        system_prompt=prompt,
        tools=tools,
        warnings=[*tool_errors, *skills.errors],
        max_steps=cfg["max_steps"],
        max_tool_output=cfg["max_tool_output"],
        memory=memory,
    )
