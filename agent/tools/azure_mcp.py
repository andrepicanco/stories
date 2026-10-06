"""Tools do servidor Azure Boards MCP (.NET): histórico, relações, buscas por responsável e relatórios do board.

As conexões vivem em agent.mcp_bridge; este módulo só expõe, ao harness, as tools já descobertas."""
from agent.base import Tool, ToolContext
from agent.mcp_bridge import manager


def get_tools(ctx: ToolContext) -> list[Tool]:
    return manager.tools("azure_mcp")
