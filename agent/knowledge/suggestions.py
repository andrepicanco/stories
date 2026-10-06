"""Sugestões de ontologia vindas da geração de um card: viram RASCUNHOS (nunca fatos confirmados).

O modelo propõe no campo `ontology_suggestions` do contrato JSON; este código valida, aplica o padrão STE-pt
(uma reescrita se houver avisos) e grava em `_rascunhos/`. Sem fonte, a sugestão é descartada."""
from pathlib import Path

from agent.knowledge import ingest
from agent.knowledge.events import _root
from agent.knowledge.store import OntologyStore

MAX_SUGGESTIONS = 3


def save_suggestions(llm, settings: dict, raw: list, sleep=None) -> list[str]:
    """Devolve os nomes dos rascunhos gravados ou atualizados."""
    root = _root(settings)
    if root is None or not raw:
        return []
    kwargs = {"sleep": sleep} if sleep else {}
    store = OntologyStore(root)
    state = ingest.load_state()
    written = state.setdefault("drafts", {})
    saved = []
    for concept in ingest.normalize_concepts({"conceitos": list(raw)[:MAX_SUGGESTIONS]}):
        if not concept["fonte"]:
            continue
        warnings = ingest.enforce_style(llm, store, concept, **kwargs)
        action = ingest.write_draft(root, store, concept, f"geracao:{concept['fonte']}", written, warnings)
        if action in ("criado", "fundido", "atualizacao"):
            saved.append(concept["nome"])
    ingest.save_state(state)
    return saved
