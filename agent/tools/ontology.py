"""Tools de leitura da ontologia de Cobrança (pasta de notas configurada em ⚙️).

Só notas validadas contam como fato. Rascunhos da IA aparecem apenas se pedidos, sempre marcados."""
from pathlib import Path

from agent.base import Param, Tool, ToolContext
from agent.knowledge.store import Note, OntologyStore
from agent.ontology import Effect

GROUP = "ontology"
SNIPPET_CHARS = 160


def configured_dir(settings: dict) -> Path | None:
    value = (settings.get("ontology", {}).get("dir") or "").strip()
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = Path(__file__).resolve().parent.parent.parent / path
    return path


def _flags(note: Note) -> str:
    out = []
    if note.is_draft:
        out.append("NÃO CONFIRMADO: rascunho")
    if note.warnings:
        out.append(f"fora do padrão STE-pt: {len(note.warnings)} avisos")
    return f" ({'; '.join(out)})" if out else ""


def _first_sentence(note: Note) -> str:
    text = " ".join(note.body.split())
    return text if len(text) <= SNIPPET_CHARS else text[:SNIPPET_CHARS - 1] + "…"


def describe(note: Note) -> str:
    lines = [f"{note.name} [{note.kind}]{_flags(note)}"]
    if note.synonyms:
        lines.append("Termos não aprovados (sinônimos): " + ", ".join(note.synonyms))
    if note.relations:
        lines.append("Relações: " + "; ".join(f"{rel} → {target}" for rel, target in note.relations))
    if note.sources:
        lines.append("Fontes: " + ", ".join(note.sources))
    if note.updated:
        lines.append(f"Atualizado em: {note.updated}")
    lines.append("\n" + (note.body or "(sem descrição)"))
    return "\n".join(lines)


def get_tools(ctx: ToolContext) -> list[Tool]:
    root = configured_dir(ctx.settings)
    if root is None or not root.is_dir():
        return []
    store = OntologyStore(root)
    drafts = Param("Text", "'sim' inclui rascunhos não confirmados da IA (padrão: não)", optional=True, enum=["sim", "nao"])

    def search(texto, incluir_rascunhos="nao"):
        with_drafts = incluir_rascunhos == "sim"
        hits = store.search(texto, include_drafts=with_drafts)
        if not hits:
            extra = store.count_drafts_matching(texto) if not with_drafts else 0
            return "nenhum conceito confirmado encontrado" + (
                f" ({extra} rascunho(s) não confirmado(s) casam; use incluir_rascunhos=sim)" if extra else "")
        out = [f"- {n.name} [{n.kind}]{_flags(n)}: {_first_sentence(n)}" for n in hits]
        hidden = store.count_drafts_matching(texto) if not with_drafts else 0
        if hidden:
            out.append(f"[+{hidden} rascunho(s) não confirmado(s); use incluir_rascunhos=sim para vê-los]")
        return "\n".join(out)

    def concept(nome):
        note = store.resolve(nome)
        if note is None:
            return f"conceito '{nome}' não encontrado; use ontologia_buscar"
        return describe(note)

    def neighbors(nome, profundidade=1, incluir_rascunhos="nao"):
        rows = store.neighbors(nome, profundidade, include_drafts=incluir_rascunhos == "sim")
        if not rows:
            return f"nenhuma relação encontrada para '{nome}'" if store.resolve(nome) else f"conceito '{nome}' não encontrado"
        return "\n".join(f"{'  ' * (level - 1)}{arrow} {rel}: {target}" for level, arrow, rel, target in rows)

    def timeline(assunto, desde=""):
        lines = store.timeline(assunto, desde)
        return "\n".join(lines) if lines else f"nenhum evento registrado para '{assunto}'" + (f" desde {desde}" if desde else "")

    return [
        Tool(
            name="ontologia_buscar",
            description="Procura conceitos, sistemas, fluxos e regras de Cobrança na ontologia do time (nome, "
                        "sinônimos e descrição). Use ANTES de redigir para entender os termos do tema.",
            inputs={"texto": Param("Query", "termo ou palavras do assunto"), "incluir_rascunhos": drafts},
            fn=search, effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="ontologia_conceito",
            description="Lê um conceito da ontologia: descrição, relações, fontes e sinônimos não aprovados. "
                        "Aceita o nome ou um sinônimo.",
            inputs={"nome": Param("Text", "nome ou sinônimo do conceito")},
            fn=concept, effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="ontologia_vizinhos",
            description="Mostra o que se liga a um conceito (→ saída, ← entrada), até 2 saltos. Use para descobrir "
                        "sistemas, regras e fluxos relacionados.",
            inputs={"nome": Param("Text", "nome ou sinônimo do conceito"),
                    "profundidade": Param("Inteiro", "1 ou 2 saltos (padrão 1)", optional=True),
                    "incluir_rascunhos": drafts},
            fn=neighbors, effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="ontologia_linha_do_tempo",
            description="Lista eventos datados (mudanças de estado de cards, implantações) sobre um assunto, do mais "
                        "novo para o mais antigo. Útil para saber o que mudou e quando.",
            inputs={"assunto": Param("Query", "conceito, sistema ou 'card:ID'"),
                    "desde": Param("Text", "data inicial AAAA-MM-DD (opcional)", optional=True)},
            fn=timeline, effect=Effect.READ, group=GROUP,
        ),
    ]
