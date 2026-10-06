"""Tools de leitura do Notion, via MCP remoto (busca e leitura de páginas, bancos de dados e comentários).

Escritas do servidor (criar/editar páginas) nunca são expostas ao agente."""
from agent.base import Tool, ToolContext
from agent.mcp_bridge import manager


def get_tools(ctx: ToolContext) -> list[Tool]:
    return manager.tools("notion_mcp")
