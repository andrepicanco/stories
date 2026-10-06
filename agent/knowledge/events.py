"""Cronologia da ontologia: `Eventos/AAAA-MM.md`, uma linha por evento, ordenada por data e sem duplicatas.

Linha: `- 2026-10-02 | card:288965 | Waiting Deploy → Done: Título do card | [[Conceito]]`.
Duas fontes: o card criado pela ferramenta e a sincronização das mudanças de estado dos cards no Azure DevOps
(leitura educada: sequencial, com teto por execução e marca d'água)."""
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from agent.knowledge import ingest, style
from agent.knowledge.store import EVENTS_DIR, OntologyStore
from integrations import azure_client as az
from integrations.board_url import InvalidBoardUrl, parse_board_url
from integrations.polite import PoliteClient

EVENT_TYPES = ("User Story", "Technical Story", "Spike", "Design Story", "Bug")
MAX_TEXT = 160
MAX_LINKS = 3
_EVENT = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\s*\|")


def _clean(text: str) -> str:
    return " ".join(str(text).replace("|", "/").split())[:MAX_TEXT]


def link_concepts(store: OntologyStore, text: str) -> list[str]:
    """Conceitos VALIDADOS cujo nome ou sinônimo aparece no texto (palavra inteira)."""
    folded = style.fold(text)
    found = []
    for note in store.notes():
        if note.is_draft:
            continue
        for term in [note.name, *note.synonyms]:
            key = style.fold(term)
            if len(key) >= 4 and re.search(rf"(?<!\w){re.escape(key)}(?!\w)", folded):
                found.append(note.name)
                break
    return found[:MAX_LINKS]


def format_event(day: str, ref: str, text: str, links: list[str]) -> str:
    line = f"- {day} | {ref} | {_clean(text)}"
    return line + (" | " + " ".join(f"[[{name}]]" for name in links) if links else "")


def add_events(root: Path, lines: list[str]) -> int:
    """Acrescenta as linhas aos arquivos mensais (sem duplicar) e mantém cada arquivo ordenado por data."""
    by_month: dict[str, list[str]] = {}
    for line in lines:
        m = _EVENT.match(line)
        if m:
            by_month.setdefault(m.group(1)[:7], []).append(line)
    added = 0
    for month, new_lines in by_month.items():
        path = root / EVENTS_DIR / f"{month}.md"
        existing = []
        if path.exists():
            existing = [l.strip() for l in path.read_text(encoding="utf-8").splitlines() if _EVENT.match(l.strip())]
        fresh = [l for l in dict.fromkeys(new_lines) if l not in existing]
        if not fresh:
            continue
        merged = sorted([*existing, *fresh], key=lambda l: _EVENT.match(l).group(1))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Eventos {month}\n\n" + "\n".join(merged) + "\n", encoding="utf-8")
        added += len(fresh)
    return added


def _root(settings: dict) -> Path | None:
    folder = (settings.get("ontology", {}).get("dir") or "").strip()
    if not folder:
        return None
    return Path(folder) if Path(folder).is_absolute() else ingest.ROOT / folder


def card_created(settings: dict, card_id: int, title: str, card_type: str, epic_id=None, epic_title: str = "") -> None:
    """Evento "card criado" ao criar o card pela ferramenta. Nunca levanta: a criação do card não pode falhar por isso."""
    try:
        root = _root(settings)
        if root is None:
            return
        text = f"criado ({card_type}): {title}" + (f" no épico #{epic_id}" if epic_id else "")
        links = link_concepts(OntologyStore(root), f"{title} {epic_title}")
        add_events(root, [format_event(date.today().isoformat(), f"card:{card_id}", text, links)])
    except Exception:  # noqa: BLE001
        ingest.log(f"evento de card criado falhou (card {card_id})")


# ---------- sincronização das mudanças de estado ----------

def _state_changes(updates: list[dict], since_day: str) -> list[tuple[str, str, str]]:
    """[(dia, estado anterior, estado novo)] das revisões do card a partir de `since_day`."""
    out = []
    for update in updates:
        state = (update.get("fields") or {}).get("System.State")
        if not state:
            continue
        stamp = ((update.get("fields") or {}).get("System.ChangedDate") or {}).get("newValue") or update.get("revisedDate") or ""
        if not stamp or stamp.startswith("9999") or stamp[:10] < since_day:
            continue
        out.append((stamp[:10], state.get("oldValue") or "", state.get("newValue") or ""))
    return out


def sync_events(settings: dict, *, dry_run: bool = True, client: PoliteClient | None = None, on_step=None,
                today: date | None = None) -> dict:
    cfg = settings.get("ontology", {})
    root = _root(settings)
    if root is None:
        raise ingest.IngestError("Configure a pasta da ontologia em ⚙️.")
    try:
        board = parse_board_url(settings["azure"]["board_url"])
    except InvalidBoardUrl as err:
        raise ingest.IngestError("Configure o Board em ⚙️.") from err
    step = on_step or (lambda s: None)
    client = client or PoliteClient()
    today = today or date.today()

    state = ingest.load_state()
    since = state.get("events", {}).get("since") or (today - timedelta(days=int(cfg.get("events_initial_days", 30)))).isoformat()
    since_day = since[:10]
    cap = int(cfg.get("events_max_items", 100))

    step({"message": f"Consultando cards alterados desde {since_day}..."})
    _, areas = az.team_area_paths(board)
    area_clause = " OR ".join(f"[System.AreaPath] {'UNDER' if sub else '='} {az._wiql_literal(p)}" for p, sub in areas)
    types = ", ".join(az._wiql_literal(t) for t in EVENT_TYPES)
    query = (f"SELECT [System.Id] FROM WorkItems WHERE [System.WorkItemType] IN ({types}) "
             f"AND [System.ChangedDate] >= '{since_day}' AND ({area_clause}) ORDER BY [System.ChangedDate] ASC")
    base = az._project_base(board)
    result = client.post_json(f"{base}/_apis/wit/wiql?api-version={az.API_VERSION}&$top={cap + 1}", {"query": query})
    ids = [row["id"] for row in result.get("workItems", [])]
    limited = len(ids) > cap
    ids = ids[:cap]
    summary = {"dry_run": dry_run, "desde": since_day, "cards_alterados": len(ids), "limitado_pelo_teto": limited,
               "requisicoes_estimadas": len(ids) + 3, "eventos_novos": 0, "erros": []}
    if dry_run or not ids:
        summary["requisicoes"] = client.requests
        ingest.log(f"eventos dry_run={dry_run} cards={len(ids)} requisicoes={client.requests}")
        return summary

    info = {}
    data = client.post_json(f"{base}/_apis/wit/workitemsbatch?api-version={az.API_VERSION}",
                            {"ids": ids, "fields": ["System.Title", "System.WorkItemType", "System.ChangedDate"], "errorPolicy": "Omit"})
    for item in data.get("value") or []:
        if item:
            info[item["id"]] = item["fields"]

    store = OntologyStore(root)
    lines, last_changed = [], since
    for i, card_id in enumerate(ids, 1):
        step({"message": f"Card {i}/{len(ids)}: #{card_id}", "done": i - 1, "total": len(ids)})
        fields = info.get(card_id, {})
        title = fields.get("System.Title", "")
        try:
            updates = client.get_json(f"{base}/_apis/wit/workitems/{card_id}/updates?api-version={az.API_VERSION}").get("value") or []
        except az.AzureError as err:
            if getattr(err, "status", None) in (401, 403, 429, 503):
                raise
            summary["erros"].append(f"#{card_id}: {err}")
            continue
        links = link_concepts(store, title)
        for day, old, new in _state_changes(updates, since_day):
            text = (f"{old} → {new}" if old else f"criado em {new}") + f": {title}"
            lines.append(format_event(day, f"card:{card_id}", text, links))
        last_changed = max(last_changed, (fields.get("System.ChangedDate") or "")[:10] or last_changed)

    summary["eventos_novos"] = add_events(root, lines)
    if not summary["erros"]:
        # Limitado pelo teto: o próximo ciclo continua dali. Completo: a marca vai até a última alteração vista.
        state.setdefault("events", {})["since"] = last_changed if limited else max(last_changed, since_day)
        ingest.save_state(state)
    summary["requisicoes"] = client.requests
    ingest.log(f"eventos cards={len(ids)} novos={summary['eventos_novos']} requisicoes={client.requests} erros={len(summary['erros'])}")
    return summary
