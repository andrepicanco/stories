"""Descoberta de tools: cada .py do diretório de tools (configurável em ⚙️) exporta
`get_tools(ctx: ToolContext) -> list[Tool]`. Arquivos que começam com `_` são ignorados."""
import importlib.util
from pathlib import Path

from .base import CORE, Tool, ToolContext


def discover_tools(tools_dir: Path, ctx: ToolContext) -> tuple[list[Tool], list[str]]:
    """Carrega as tools do diretório. Módulos com erro não derrubam os demais: viram avisos."""
    tools: list[Tool] = []
    errors: list[str] = []
    seen: set[str] = set()
    tools_dir = Path(tools_dir)
    if not tools_dir.is_dir():
        return tools, [f"diretório de tools não encontrado: {tools_dir}"]

    for file in sorted(tools_dir.glob("*.py")):
        if file.name.startswith("_"):
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"stories_tools_{file.stem}", file)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            if not hasattr(module, "get_tools"):
                errors.append(f"{file.name}: não define get_tools(ctx)")
                continue
            for tool in module.get_tools(ctx):
                if tool.name in seen:
                    errors.append(f"{file.name}: tool duplicada '{tool.name}' ignorada")
                    continue
                seen.add(tool.name)
                tools.append(tool)
        except Exception as e:  # noqa: BLE001 - qualquer falha de um módulo vira aviso
            errors.append(f"{file.name}: {type(e).__name__}: {e}")
    return tools, errors


def filter_tools(tools: list[Tool], enabled_groups: list[str]) -> list[Tool]:
    """Allowlist por execução: tools `core` sempre; as demais só se o grupo estiver marcado."""
    allowed = set(enabled_groups) | {CORE}
    return [t for t in tools if t.group in allowed]


def count_by_group(tools: list[Tool]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for tool in tools:
        counts[tool.group] = counts.get(tool.group, 0) + 1
    return counts
