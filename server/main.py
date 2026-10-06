"""Servidor FastAPI da ferramenta Stories. Serve o front estático e a API."""
import mimetypes
import threading
from contextlib import asynccontextmanager
from dataclasses import asdict
from html import escape
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agent import mcp_setup
from agent.generation import GenerationInput, generate
from agent.knowledge import events as ontology_events
from agent.knowledge import ingest as ontology_ingest_module
from agent.knowledge.store import OntologyStore
from agent.llm import LLM
from agent.mcp_bridge import manager
from agent.prompts import DEFAULT_PERSONA
from agent.service import build_agent
from integrations import azure_client
from integrations.board_url import InvalidBoardUrl, parse_board_url
from integrations.html_sanitize import sanitize_html
from integrations.html_text import html_to_text
from integrations.notion_oauth import NotionAuthError
from integrations.wiki_url import InvalidWikiUrl, parse_wiki_url

from . import cards, history, settings
from .jobs import jobs

settings.load_dotenv()
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("text/javascript", ".mjs")   # módulos ES do editor: o navegador exige tipo JavaScript

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Sobe as conexões MCP em segundo plano ao iniciar e as encerra ao parar."""
    mcp_setup.apply_settings(settings.load_settings())
    yield
    manager.close()


app = FastAPI(title="Stories", lifespan=lifespan)


class DraftIn(BaseModel):
    title: str
    state: dict


class RelatedIn(BaseModel):
    id: int
    title: str = ""


class RunIn(BaseModel):
    """Estado da tela enviado ao agente (Gerar e Responder usam o mesmo formato)."""
    story_id: str
    card_type: str = "User Story"
    epic_id: int | None = None
    epic_title: str = ""
    related: list[RelatedIn] = []
    brief: str = ""
    tools: dict[str, bool] = {}
    title: str = ""
    card_html: str = ""
    resources_html: str = ""
    criteria_html: str = ""
    chat: list[dict] = []
    reply: str = ""


def _board_context(board_url: str) -> dict | None:
    try:
        return parse_board_url(board_url).to_dict()
    except InvalidBoardUrl:
        return None


def _public_settings() -> dict:
    data = settings.load_settings()
    return {
        "settings": data,
        "board": _board_context(data["azure"]["board_url"]),
        "secrets": settings.secrets_status(),
        "defaults": {"system_prompt": DEFAULT_PERSONA},
    }


@app.get("/api/bootstrap")
def bootstrap() -> dict:
    return {**_public_settings(), "recent": history.list_recent()}


@app.get("/api/settings")
def get_settings() -> dict:
    return _public_settings()


@app.put("/api/settings")
def put_settings(patch: dict) -> dict:
    wiki_url = patch.get("azure", {}).get("wiki_url")
    if wiki_url and wiki_url.strip():
        try:
            parse_wiki_url(wiki_url)
        except InvalidWikiUrl as err:
            raise HTTPException(422, str(err)) from err
    ontology_dir = (patch.get("ontology", {}).get("dir") or "").strip()
    if ontology_dir and Path(ontology_dir).is_file():
        raise HTTPException(422, "A pasta da ontologia aponta para um arquivo, não para uma pasta.")
    board_url = patch.get("azure", {}).get("board_url")
    if board_url is not None:
        if not board_url.strip():
            raise HTTPException(422, "O campo Board é obrigatório.")
        try:
            parse_board_url(board_url)
        except InvalidBoardUrl as err:
            raise HTTPException(422, str(err)) from err
    settings.save_settings(patch)
    mcp_setup.apply_settings(settings.load_settings())   # reconecta só o que mudou
    return _public_settings()


def _mcp_item(name: str, off_message: str) -> dict:
    info = manager.status().get(name)
    if info is None or info["state"] == "disabled":
        return {"ok": False, "state": "disabled", "detail": off_message}
    return {"ok": info["state"] == "connected", "state": info["state"],
            "detail": info["error"] or f"{info['tools']} tools disponíveis"}


@app.get("/api/status")
def status() -> dict:
    """Estado das conexões exibido na sidebar."""
    secrets = settings.secrets_status()
    return {
        "azure_openai": {"ok": secrets["AZURE_OPENAI_API_KEY"], "state": "ok" if secrets["AZURE_OPENAI_API_KEY"] else "disabled",
                         "detail": "" if secrets["AZURE_OPENAI_API_KEY"] else "Defina AZURE_OPENAI_* no .env"},
        "azure_devops_rest": {"ok": secrets["AZDO_PAT"], "state": "ok" if secrets["AZDO_PAT"] else "disabled",
                              "detail": "" if secrets["AZDO_PAT"] else "Defina AZDO_PAT no .env"},
        "azure_devops_mcp": _mcp_item("azure_mcp", "Configure o Board, o AZDO_PAT e o servidor Azure Boards MCP"),
        "notion_mcp": _mcp_item("notion_mcp", "Informe a URL do servidor Notion MCP"),
    }


@app.get("/api/oauth/notion/start")
def notion_start(request: Request):
    """Inicia a autorização do Notion: redireciona o navegador para a tela de consentimento."""
    redirect_uri = str(request.base_url) + "api/oauth/notion/callback"
    try:
        return RedirectResponse(mcp_setup.notion_oauth(settings.load_settings()).begin(redirect_uri))
    except NotionAuthError as err:
        return HTMLResponse(f"<h3>Não foi possível iniciar a conexão com o Notion</h3><p>{escape(str(err))}</p>", 502)


@app.get("/api/oauth/notion/callback")
def notion_callback(code: str = "", state: str = "", error: str = ""):
    if error or not code:
        return HTMLResponse(f"<h3>Autorização recusada ou incompleta</h3><p>{escape(error or 'sem código')}</p>"
                            '<p><a href="/">Voltar</a></p>', 400)
    try:
        mcp_setup.notion_oauth(settings.load_settings()).complete(code, state)
    except NotionAuthError as err:
        return HTMLResponse(f"<h3>Falha ao concluir a conexão</h3><p>{escape(str(err))}</p>"
                            '<p><a href="/">Voltar</a></p>', 400)
    manager.restart("notion_mcp")
    return RedirectResponse("/?notion=connected")


def _board_ctx():
    try:
        return parse_board_url(settings.load_settings()["azure"]["board_url"])
    except InvalidBoardUrl as err:
        raise HTTPException(422, f"Configure o Board em ⚙️. {err}") from err


@app.get("/api/epics")
def epics() -> list[dict]:
    """Épicos do time nas colunas ativas configuradas."""
    ctx = _board_ctx()
    try:
        return azure_client.list_epics(ctx, settings.load_settings()["azure"]["epic_active_columns"])
    except azure_client.AzureError as err:
        raise HTTPException(502, str(err)) from err


@app.get("/api/epics/{epic_id}/children")
def epic_children(epic_id: int) -> list[dict]:
    ctx = _board_ctx()
    try:
        return azure_client.list_children(ctx, epic_id)
    except azure_client.AzureError as err:
        raise HTTPException(502, str(err)) from err


@app.get("/api/azure/epic-columns")
def epic_columns(board_url: str | None = None) -> list[dict]:
    """Colunas do board de Épicos. Aceita a URL do formulário, ainda não salva."""
    url = board_url or settings.load_settings()["azure"]["board_url"]
    try:
        ctx = parse_board_url(url)
        return azure_client.list_epic_columns(ctx)
    except InvalidBoardUrl as err:
        raise HTTPException(422, str(err)) from err
    except azure_client.AzureError as err:
        raise HTTPException(502, str(err)) from err


class CardIn(BaseModel):
    story_id: str
    card_type: str = "User Story"
    epic_id: int | None = None
    related: list[int] = []
    title: str = ""
    card_html: str = ""
    resources_html: str = ""
    criteria_html: str = ""
    dry_run: bool = False      # ensaio: valida e monta o payload sem criar nada


_create_lock = threading.Lock()   # criações são raras; serializar evita card duplicado por duplo clique


@app.post("/api/cards")
def create_card(body: CardIn) -> dict:
    """Botão Criar card: cria o work item no board configurado e trava a história."""
    ctx = _board_ctx()
    with _create_lock:
        story = history.get(body.story_id)
        if story is None:
            raise HTTPException(404, "História não encontrada.")
        if story["status"] == "created":
            raise HTTPException(409, "Esta história já foi criada no Azure DevOps.")
        req = cards.CardRequest(body.card_type, body.epic_id, body.related, body.title,
                                body.card_html, body.resources_html, body.criteria_html)
        try:
            prepared = cards.prepare(ctx, settings.load_settings(), req)
            if body.dry_run:
                return {"dry_run": True, "type": prepared.work_item_type, "title": prepared.title,
                        "patch": prepared.patch, "warnings": prepared.warnings}
            result = cards.create(ctx, prepared)
        except cards.CardError as err:
            raise HTTPException(err.status, str(err)) from err
        except azure_client.AzureError as err:
            raise HTTPException(502, f"Azure DevOps: {err}") from err
        try:
            history.mark_created(body.story_id, result["id"], result["url"], result["title"])
        except Exception as err:  # noqa: BLE001 - o card JÁ existe no Azure: não perder essa informação
            result["warnings"].append(f"Card criado (#{result['id']}), mas não foi possível travar a história: {err}")
        ontology_events.card_created(settings.load_settings(), result["id"], result["title"], body.card_type, body.epic_id)
        return result


GROUPS = ("notion", "azure", "obsidian")


def _start_run(body: RunIn, require_reply: bool) -> dict:
    story = history.get(body.story_id)
    if story is None:
        raise HTTPException(404, "História não encontrada.")
    if story["status"] == "created":
        raise HTTPException(409, "Esta história já foi criada no Azure DevOps e não pode ser alterada.")
    if body.card_type not in settings.load_settings()["azure"]["work_item_types"]:
        raise HTTPException(422, f"Tipo de card inválido: {body.card_type}")
    # Brief e resposta chegam como HTML do editor; o agente recebe texto limpo (links preservados).
    brief = html_to_text(sanitize_html(body.brief))
    reply = html_to_text(sanitize_html(body.reply))
    if require_reply and not reply:
        raise HTTPException(422, "Digite uma resposta para a iteração.")
    if not require_reply and not brief:
        raise HTTPException(422, "Descreva o objetivo do card em 'Descrição breve'.")

    inp = GenerationInput(
        card_type=body.card_type,
        epic={"id": body.epic_id, "title": body.epic_title} if body.epic_id else None,
        related=[r.model_dump() for r in body.related],
        brief=brief,
        enabled_groups=[g for g in GROUPS if body.tools.get(g)],
        title=body.title,
        card_html=sanitize_html(body.card_html),
        resources_html=sanitize_html(body.resources_html),
        criteria_html=sanitize_html(body.criteria_html),
        chat=[c for c in body.chat if c.get("role") in ("assistant", "user") and isinstance(c.get("content"), str)],
        reply=reply,
    )

    def work(on_step):
        result = generate(
            LLM(), settings.load_settings(), inp,
            on_step=lambda s: on_step({"tool": s.tool, "args": s.args[:200], "error": s.error}),
        )
        return asdict(result)

    return jobs.start(work).public()


@app.post("/api/generate")
def generate_card(body: RunIn) -> dict:
    """Botão Gerar: inicia a execução do agente e devolve o job para acompanhamento."""
    return _start_run(body, require_reply=False)


@app.post("/api/reply")
def reply_to_agent(body: RunIn) -> dict:
    """Botão Responder: reenvia os textos atuais junto com a resposta do usuário."""
    return _start_run(body, require_reply=True)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Execução não encontrada (o servidor pode ter sido reiniciado).")
    return job.public()


class IngestIn(BaseModel):
    dry_run: bool = True          # ensaio: conta páginas e estima tokens, sem chamar o modelo
    limit: int | None = None      # processa só as N primeiras páginas alteradas
    notion: bool = False
    force: bool = False           # ignora "nada mudou" (mesmo commit)


_ingest_job: dict = {"id": None}


@app.post("/api/ontology/ingest")
def ontology_ingest(body: IngestIn) -> dict:
    """Constrói/atualiza a ontologia em rascunhos. Uma execução por vez, só quando o usuário pede."""
    current = jobs.get(_ingest_job["id"]) if _ingest_job["id"] else None
    if current is not None and current.status == "running":
        raise HTTPException(409, "Já existe uma ingestão em andamento.")
    cfg = settings.load_settings()
    if not (cfg.get("ontology", {}).get("dir") or "").strip():
        raise HTTPException(422, "Configure a pasta da ontologia em ⚙️.")

    def work(on_step):
        llm = None if body.dry_run else LLM()
        return ontology_ingest_module.run_ingest(llm, cfg, dry_run=body.dry_run, limit=body.limit, force=body.force,
                                                 include_notion=body.notion, on_step=on_step)

    job = jobs.start(work)
    _ingest_job["id"] = job.id
    return job.public()


class SyncIn(BaseModel):
    dry_run: bool = True


@app.post("/api/ontology/sync-events")
def ontology_sync_events(body: SyncIn) -> dict:
    """Registra na cronologia as mudanças de estado dos cards (leitura educada, com ensaio)."""
    current = jobs.get(_ingest_job["id"]) if _ingest_job["id"] else None
    if current is not None and current.status == "running":
        raise HTTPException(409, "Já existe uma ingestão ou sincronização em andamento.")
    cfg = settings.load_settings()

    def work(on_step):
        return ontology_events.sync_events(cfg, dry_run=body.dry_run, on_step=on_step)

    job = jobs.start(work)
    _ingest_job["id"] = job.id
    return job.public()


@app.get("/api/ontology/lint")
def ontology_lint() -> dict:
    """Relatório do padrão STE-pt: notas com avisos (inclusive as editadas à mão) e contagens."""
    folder = (settings.load_settings().get("ontology", {}).get("dir") or "").strip()
    if not folder or not Path(folder).is_dir():
        return {"configured": False, "notes": 0, "drafts": 0, "with_warnings": []}
    notes = OntologyStore(Path(folder)).notes()
    return {
        "configured": True, "notes": len(notes), "drafts": sum(n.is_draft for n in notes),
        "with_warnings": [{"path": n.path, "status": n.status, "warnings": n.warnings} for n in notes if n.warnings],
    }


@app.get("/api/agent/info")
def agent_info() -> dict:
    """O que o agente enxerga com todas as fontes habilitadas: tools, skills, avisos e o prompt montado."""
    manager.wait_ready(20)
    agent = build_agent(settings.load_settings(), ["notion", "azure", "obsidian"])
    return {
        "mcp": manager.status(),
        "tools": [{"name": t.name, "group": t.group, "effect": t.effect.value} for t in agent.tools],
        "warnings": agent.warnings,
        "system_prompt": agent.system_prompt,
        "limits": {"max_steps": agent.max_steps, "max_tool_output": agent.max_tool_output},
    }


@app.get("/api/history")
def list_history() -> list[dict]:
    return history.list_recent()


@app.post("/api/history")
def new_story() -> dict:
    return history.create()


@app.get("/api/history/{story_id}")
def get_story(story_id: str) -> dict:
    story = history.get(story_id)
    if story is None:
        raise HTTPException(404, "História não encontrada.")
    return story


@app.delete("/api/history/{story_id}")
def delete_story(story_id: str) -> dict:
    """Remove da lista local de recentes. O card no Azure DevOps (se existir) não é afetado."""
    if not history.delete(story_id):
        raise HTTPException(404, "História não encontrada.")
    return {"ok": True}


@app.put("/api/drafts/{story_id}")
def put_draft(story_id: str, body: DraftIn) -> dict:
    story = history.save_draft(story_id, body.title, body.state)
    if story is None:
        raise HTTPException(404, "História não encontrada.")
    return story


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
