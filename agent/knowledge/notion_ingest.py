"""Ingestão a partir do Notion: um turno limitado do agente (só tools de leitura) que explora a partir da
página raiz configurada e devolve conceitos no mesmo esquema da wiki, cada um com sua fonte.

Cuidados: tools sequenciais com intervalo, teto de leituras por execução, saída com segredos é omitida
antes de chegar ao modelo, e conceitos sem fonte são descartados."""
import dataclasses
import time
from pathlib import Path

from agent import generation
from agent.harness import run_turn
from agent.knowledge import ingest
from agent.knowledge.secrets import find_secrets
from agent.knowledge.store import OntologyStore
from agent.mcp_bridge import manager

MAX_READS = 20


def _guarded(tool, state: dict, sleep):
    """Mesma tool, com intervalo entre chamadas, teto de leituras e filtro de segredos na saída."""
    original = tool.fn

    def fn(**args):
        state["calls"] += 1
        if state["calls"] > MAX_READS:
            return "limite de leituras do Notion nesta execução atingido: finalize com o que já leu"
        sleep(0.5)
        out = str(original(**args))
        return "[conteúdo omitido: contém segredos]" if find_secrets(out) else out

    return dataclasses.replace(tool, fn=fn)


def run(llm, settings: dict, root: Path, step, sleep, summary: dict) -> dict:
    root_page = settings["notion"].get("root_page", "").strip()
    if not root_page:
        return {"observacao": "Informe a página raiz do Notion em ⚙️ para ingerir o Notion."}
    manager.wait_ready(20)
    tools = manager.tools("notion_mcp")
    if not tools:
        return {"observacao": "Notion indisponível (não conectado)."}
    state = {"calls": 0}
    guarded = [_guarded(t, state, sleep) for t in tools]
    system = ingest.EXTRACTION_SYSTEM + (
        "\n\nNesta tarefa você PODE usar as tools do Notion para ler páginas, a partir da página raiz indicada. "
        f"Leia no máximo {MAX_READS} páginas e escolha as de maior valor de domínio. Cada conceito deve ter o campo "
        '"fonte" (título ou URL da página do Notion de onde veio); sem fonte, não o inclua.')
    step({"message": "Notion: explorando a partir da página raiz..."})
    result = run_turn(llm, system, [{"role": "user", "content": f"Página raiz do Notion: {root_page}"}], guarded,
                      max_steps=int(settings["agent"].get("max_steps", 12)),
                      max_tool_output=int(settings["agent"].get("max_tool_output", 8000)))
    try:
        data = generation._extract_json(result.text)
    except Exception as err:  # noqa: BLE001 - JSON ilegível vira relatório, não erro
        return {"erro": f"resposta ilegível: {err}"}

    store = OntologyStore(root)
    state_full = ingest.load_state()
    written = state_full.setdefault("drafts", {})
    counts, discarded = {}, 0
    for concept in ingest.normalize_concepts(data):
        source = concept["fonte"]
        if not source:
            discarded += 1
            continue
        warnings = ingest.enforce_style(llm, store, concept, sleep)
        action = ingest.write_draft(root, store, concept, f"notion:{source}", written, warnings)
        counts[action] = counts.get(action, 0) + 1
    ingest.save_state(state_full)
    ingest.log(f"notion leituras={state['calls']} drafts={counts} sem_fonte={discarded}")
    return {"leituras": state["calls"], "drafts": counts, "descartados_sem_fonte": discarded}
