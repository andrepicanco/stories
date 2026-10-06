"""Tools de leitura do Azure DevOps via API REST direta (cards do board configurado)."""
import os

from agent.base import Param, Tool, ToolContext
from agent.ontology import Effect
from integrations import azure_client as az
from integrations.board_url import InvalidBoardUrl, parse_board_url
from integrations.html_text import html_to_text

GROUP = "azure"
LINK_LABELS = {
    "System.LinkTypes.Hierarchy-Reverse": "pai",
    "System.LinkTypes.Hierarchy-Forward": "filho",
    "System.LinkTypes.Related": "relacionado",
}


def _describe(ctx, item: dict) -> str:
    f = item["fields"]
    lines = [
        f"#{item['id']} [{f.get('System.WorkItemType', '?')}] {f.get('System.Title', '')}",
        f"Estado: {f.get('System.State', '?')} | Área: {f.get('System.AreaPath', '?')}",
        f"URL: {az.work_item_url(ctx, item['id'])}",
    ]
    description = html_to_text(f.get("System.Description"))
    if description:
        lines.append(f"\nDescrição:\n{description}")
    criteria = html_to_text(f.get("Microsoft.VSTS.Common.AcceptanceCriteria"))
    if criteria:
        lines.append(f"\nCritérios de aceite:\n{criteria}")
    resources = html_to_text(f.get("Custom.c60efaaa-0bd7-448e-a0fc-72a42091c66b"))
    if resources:
        lines.append(f"\nRecursos impactados / repositórios:\n{resources}")
    links = []
    for relation in item.get("relations") or []:
        label = LINK_LABELS.get(relation.get("rel"))
        if label:
            links.append(f"{label} #{relation['url'].rstrip('/').rsplit('/', 1)[1]}")
    if links:
        lines.append("\nLinks: " + ", ".join(links))
    return "\n".join(lines)


def get_tools(ctx: ToolContext) -> list[Tool]:
    try:
        board = parse_board_url(ctx.settings["azure"]["board_url"])
    except InvalidBoardUrl:
        return []
    if not os.environ.get("AZDO_PAT"):
        return []
    return [
        Tool(
            name="azure_get_work_item",
            description="Lê um card do Azure DevOps pelo ID: título, tipo, estado, descrição, critérios de aceite, "
                        "recursos impactados e links (pai, filhos, relacionados).",
            inputs={"id": Param("WorkItemId", "ID numérico do work item")},
            fn=lambda id: _describe(board, az.get_work_item(board, id)),
            effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="azure_list_epic_children",
            description="Lista os cards filhos diretos de um épico (id, tipo, estado, título).",
            inputs={"epic_id": Param("WorkItemId", "ID do épico")},
            fn=lambda epic_id: "\n".join(
                f"#{c['id']} [{c['type']}] {c['state']} — {c['title']}" for c in az.list_children(board, epic_id)
            ) or "o épico não tem cards filhos",
            effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="azure_search_work_items",
            description="Busca cards do projeto cujo título contém o texto (mais recentes primeiro, até 15).",
            inputs={"text": Param("Query", "texto a procurar no título")},
            fn=lambda text: "\n".join(
                f"#{c['id']} [{c['type']}] {c['state']} — {c['title']}" for c in az.search_work_items(board, text)
            ) or "nenhum card encontrado",
            effect=Effect.READ, group=GROUP,
        ),
    ]
