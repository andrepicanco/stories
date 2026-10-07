"""Tools de leitura da wiki do Azure DevOps, confinadas à página raiz configurada em ⚙️."""
import os

from agent.base import Param, Tool, ToolContext
from agent.ontology import Effect
from integrations import azure_client as az
from integrations.wiki_url import InvalidWikiUrl, parse_wiki_url

GROUP = "azure"   # liga e desliga junto do checkbox Azure DevOps


def get_tools(ctx: ToolContext) -> list[Tool]:
    try:
        wiki = parse_wiki_url(ctx.settings["azure"].get("wiki_url", ""))
    except InvalidWikiUrl:
        return []
    if not os.environ.get("AZDO_PAT"):
        return []
    path = Param("Path", "caminho da página relativo à raiz da wiki, ex.: 'Cobranca/Regras'; vazio = a própria raiz",
                 optional=True)
    return [
        Tool(
            name="wiki_list_pages",
            description="Lista as páginas filhas diretas de uma página da wiki do time (caminhos relativos à raiz).",
            inputs={"path": path},
            fn=lambda path="": "\n".join(az.wiki_list_pages(wiki, path)) or "a página não tem subpáginas",
            effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="wiki_read_page",
            description="Lê o conteúdo (markdown) de uma página da wiki do time.",
            inputs={"path": path},
            fn=lambda path="": az.wiki_get_page(wiki, path) or "página sem conteúdo",
            effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="wiki_search",
            description="Procura páginas da wiki do time pelo título/caminho (todas as palavras, sem acento; até 10 "
                        "resultados relativos à raiz). Não busca dentro do conteúdo: depois leia a página com wiki_read_page.",
            inputs={"text": Param("Query", "palavras do título ou do caminho")},
            fn=lambda text: "\n".join(az.wiki_search(wiki, text)) or "nenhuma página encontrada",
            effect=Effect.READ, group=GROUP,
        ),
    ]
