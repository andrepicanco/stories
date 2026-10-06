"""System prompt: persona (editável em ⚙️) + regras fixas do harness + skills + fontes + memória."""
from datetime import date

DEFAULT_PERSONA = (
    "Você é um redator técnico de cards do Azure Boards (User Story, Technical Story e Spike). "
    "Escreve em português do Brasil, de forma objetiva, e seus textos são consumidos por pessoas e por "
    "IAs durante o refinamento técnico, então precisão e completude do escopo são essenciais."
)

HARNESS_RULES = """## Regras de trabalho
- Fundamente cada afirmação técnica em fatos obtidos pelas tools ou informados pelo usuário. Nunca invente \
nomes de sistemas, tabelas, repositórios, pessoas, datas ou decisões.
- Se o usuário indicou arquivos, links ou locais de contexto, leia-os primeiro com as tools disponíveis.
- Quando uma informação necessária não for encontrada, diga isso explicitamente em vez de preencher a lacuna.
- Antes de redigir, se faltar informação essencial que as fontes não resolvem, você pode devolver no máximo \
2 perguntas de validação e NÃO gerar o texto do card ainda. Se as fontes bastam, gere o texto completo e \
registre suposições e dúvidas menores no comentário de iteração.
- Use somente as fontes de contexto listadas abaixo."""

GROUP_LABELS = {
    "notion": "Notion",
    "azure": "Azure DevOps",
    "obsidian": "Obsidian (anotações locais)",
}


def build_system_prompt(
    persona: str,
    skills_block: str,
    memory_block: str,
    enabled_groups: list[str],
    tools_by_group: dict[str, int],
    today: date | None = None,
    notion_root: str = "",
) -> str:
    sources = []
    for group in enabled_groups:
        label = GROUP_LABELS.get(group, group)
        if tools_by_group.get(group, 0):
            hint = f" (página raiz do projeto: {notion_root}; prefira buscar dentro dela)" if group == "notion" and notion_root else ""
            sources.append(f"- {label}: disponível{hint}")
        else:
            sources.append(f"- {label}: indisponível nesta execução (não configurada ou sem conexão)")
    if not sources:
        sources.append("- Nenhuma fonte externa habilitada: use apenas o que o usuário informou.")

    parts = [
        (persona or DEFAULT_PERSONA).strip(),
        HARNESS_RULES,
        "## Fontes de contexto habilitadas\n" + "\n".join(sources),
        skills_block,
        memory_block,
        f"Data de hoje: {(today or date.today()).isoformat()}.",
    ]
    return "\n\n".join(p for p in parts if p)
