"""Tool de leitura do glossário de domínio (Cobrança): resolve siglas, abreviações, sinônimos e jargão interno.

O glossário vem de um JSON gerado da planilha por scripts/glossario_build.py e configurado em ⚙️ (glossary.path).
Só a entrada que casou volta ao modelo; o glossário em si nunca entra no prompt. Sem arquivo configurado, nenhuma
tool é registrada."""
from pathlib import Path

from agent.base import CORE, Param, Tool, ToolContext
from agent.glossary import Glossary, load_entries
from agent.ontology import Effect

GROUP = CORE   # sem checkbox na tela: o filtro por grupo (registry.filter_tools) bloquearia qualquer outro nome

SEARCH_HINT = ("Ao buscar nas fontes, tente o nome canônico e cada sinônimo em buscas separadas "
               "(as buscas exigem que TODOS os termos estejam presentes).")


def _describe(entry: dict) -> str:
    lines = [f"{entry['nome_canonico']} ({entry.get('tipo', '?')})"]
    if entry.get("sinonimos"):
        lines.append("  Sinônimos: " + "; ".join(entry["sinonimos"]))
    if entry.get("nota"):
        lines.append(f"  Nota: {entry['nota']}")
    return "\n".join(lines)


def lookup(glossary: Glossary, term: str) -> str:
    matches = glossary.lookup(term)
    if not matches:
        return (f"'{term}' não consta no glossário (busca exata no nome canônico e nos sinônimos, sem aproximação). "
                "Siga com o termo como veio e registre no comentário que ele não foi resolvido.")
    head = f"'{term}' casa com {len(matches)} entradas (desambigue pelo contexto do pedido):\n" if len(matches) > 1 else ""
    return head + "\n".join(_describe(e) for e in matches) + "\n" + SEARCH_HINT


def get_tools(ctx: ToolContext) -> list[Tool]:
    configured = (ctx.settings.get("glossary", {}).get("path") or "").strip()
    if not configured:
        return []
    path = Path(configured)
    if not path.is_absolute():
        path = ctx.root / path
    if not path.is_file():
        return []
    entries = load_entries(path)   # arquivo inválido vira aviso em discover_tools, sem derrubar as outras tools
    if not entries:
        return []
    glossary = Glossary(entries)
    return [
        Tool(
            name="glossario_buscar",
            description="Consulta o glossário de Cobrança: devolve nome canônico, tipo, sinônimos e nota do termo. Use "
                        "sempre que houver um termo desconhecido, que não faça sentido ou que pareça sigla, "
                        "abreviação ou jargão (ex.: 'reneg', 'birô'), ANTES de buscar nas fontes. Um termo por "
                        "chamada; a busca é exata (sem distinguir acentos nem maiúsculas) no nome canônico e nos sinônimos.",
            inputs={"term": Param("Query", "o termo, sigla ou abreviação a resolver")},
            fn=lambda term: lookup(glossary, term),
            effect=Effect.READ, group=GROUP,
        ),
    ]
