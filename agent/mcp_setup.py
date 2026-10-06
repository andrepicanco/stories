"""Traduz as configurações em conexões MCP: Azure Boards (.NET, stdio) e Notion (remoto, OAuth)."""
import json
import os
from pathlib import Path

from integrations.board_url import InvalidBoardUrl, parse_board_url
from integrations.notion_oauth import NotionOAuth

from .mcp_bridge import ServerSpec, http_transport, manager, stdio_transport

ROOT = Path(__file__).resolve().parent.parent
NOTION_AUTH_FILE = ROOT / "storage" / "notion-auth.json"
AZURE_MCP_LOG = ROOT / "storage" / "azure-mcp.log"

# Duplicadas pelas tools REST (azure_get_work_item e azure_search_work_items), que trazem mais campos.
AZURE_HIDDEN = frozenset({"get_work_item", "search_work_items_by_title"})
# O servidor do Notion expõe ~26 tools de leitura (sessões, agentes, skills...). O agente só recebe
# as de busca e leitura de conteúdo: menos ruído no contexto e menos chance de o modelo se perder.
NOTION_TOOLS = frozenset({
    "notion-search", "notion-fetch", "notion-get-comments", "notion-query-data-sources",
    "notion-query-meeting-notes", "notion-get-teams", "notion-get-users",
})


def notion_oauth(settings: dict) -> NotionOAuth:
    return NotionOAuth(NOTION_AUTH_FILE, settings["notion"]["server_url"])


def build_specs(settings: dict) -> tuple[dict, dict]:
    """(specs, unauthorized). Spec None = servidor desligado por falta de configuração."""
    specs: dict = {"azure_mcp": None, "notion_mcp": None}
    unauthorized: dict = {}

    cfg = settings.get("azure_mcp", {})
    pat = os.environ.get("AZDO_PAT", "")
    try:
        board = parse_board_url(settings["azure"]["board_url"])
    except InvalidBoardUrl:
        board = None
    if board and pat and cfg.get("command") and cfg.get("args"):
        env = {"AZDO_ORG_URL": board.org_url, "AZDO_PROJECT": board.project, "AZDO_PAT": pat}
        specs["azure_mcp"] = ServerSpec(
            name="azure_mcp", group="azure", prefix="azure_boards",
            open_transport=stdio_transport(cfg["command"], list(cfg["args"]), env, AZURE_MCP_LOG),
            hidden_names=AZURE_HIDDEN,
            fingerprint=json.dumps([cfg["command"], cfg["args"], board.org_url, board.project, hash(pat)]),
        )

    url = settings["notion"]["server_url"].strip()
    if url:
        oauth = notion_oauth(settings)
        specs["notion_mcp"] = ServerSpec(
            name="notion_mcp", group="notion", prefix="notion",
            open_transport=http_transport(url, oauth.access_token),
            only_names=NOTION_TOOLS,
            fingerprint=json.dumps([url, oauth.is_connected()]),
        )
        if not oauth.is_connected():
            unauthorized["notion_mcp"] = "Notion não autorizado. Clique em conectar."
    return specs, unauthorized


def apply_settings(settings: dict) -> None:
    specs, unauthorized = build_specs(settings)
    manager.configure(specs, unauthorized)
