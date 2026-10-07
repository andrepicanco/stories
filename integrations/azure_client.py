"""Cliente REST do Azure DevOps (stdlib). O PAT vem de AZDO_PAT e nunca é logado."""
import base64
import json
import os
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .board_url import BoardContext
from .wiki_url import WikiContext

API_VERSION = "7.1"
TIMEOUT_SECONDS = 30
BATCH_SIZE = 200


class AzureError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def _quote(value) -> str:
    return urllib.parse.quote(str(value), safe="")


def _auth_header() -> str:
    pat = os.environ.get("AZDO_PAT", "")
    if not pat:
        raise AzureError("AZDO_PAT não está definido (.env ou variável de ambiente).")
    return "Basic " + base64.b64encode(f":{pat}".encode()).decode()


def _request(method: str, url: str, body=None, content_type: str = "application/json") -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Authorization": _auth_header(), "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")[:300]
        if err.code in (401, 403):
            raise AzureError("PAT inválido, expirado ou sem permissão para esta operação.", err.code) from err
        raise AzureError(f"Azure DevOps respondeu {err.code}: {detail}", err.code) from err
    except urllib.error.URLError as err:
        raise AzureError(f"Não foi possível conectar ao Azure DevOps: {err.reason}") from err


def _get(url: str) -> dict:
    return _request("GET", url)


def _project_base(ctx: BoardContext) -> str:
    return f"{ctx.org_url}/{_quote(ctx.project)}"


def _team_base(ctx: BoardContext) -> str:
    return f"{_project_base(ctx)}/{_quote(ctx.team)}/_apis/work"


def work_item_url(ctx: BoardContext, work_item_id: int) -> str:
    return f"{_project_base(ctx)}/_workitems/edit/{work_item_id}"


# ---------- Boards e colunas ----------

def list_boards(ctx: BoardContext) -> list[dict]:
    """Boards (níveis de backlog) do time: Epics, Features, Stories etc."""
    return _get(f"{_team_base(ctx)}/boards?api-version={API_VERSION}").get("value", [])


def find_epic_board(ctx: BoardContext) -> dict:
    boards = list_boards(ctx)
    for board in boards:
        if board["name"].strip().lower() in ("epics", "epicos", "épicos"):
            return board
    for board in boards:
        if "epic" in board["name"].lower() or "épic" in board["name"].lower():
            return board
    names = ", ".join(b["name"] for b in boards) or "nenhum"
    raise AzureError(f"Board de Épicos não encontrado para o time '{ctx.team}'. Boards disponíveis: {names}.")


def list_epic_columns(ctx: BoardContext) -> list[dict]:
    """Colunas do board de Épicos do time, na ordem do board."""
    board = find_epic_board(ctx)
    data = _get(f"{_team_base(ctx)}/boards/{_quote(board['id'])}/columns?api-version={API_VERSION}")
    return [{"id": c.get("id"), "name": c["name"], "type": c.get("columnType")} for c in data.get("value", [])]


# ---------- Épicos e filhos ----------

def team_area_paths(ctx: BoardContext) -> tuple[str, list[tuple[str, bool]]]:
    """(area padrão do time, [(area, inclui_filhas)])."""
    data = _get(f"{_team_base(ctx)}/teamsettings/teamfieldvalues?api-version={API_VERSION}")
    values = [(v["value"], bool(v.get("includeChildren"))) for v in data.get("values", [])]
    if not values:
        raise AzureError(f"O time '{ctx.team}' não tem area paths configurados.")
    return data.get("defaultValue") or values[0][0], values


def _wiql_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _batch_fields(ctx: BoardContext, ids: list[int], fields: list[str]) -> dict[int, dict]:
    """Busca campos em lotes. Itens inexistentes ou sem acesso são omitidos."""
    result: dict[int, dict] = {}
    for start in range(0, len(ids), BATCH_SIZE):
        data = _request(
            "POST",
            f"{_project_base(ctx)}/_apis/wit/workitemsbatch?api-version={API_VERSION}",
            {"ids": ids[start:start + BATCH_SIZE], "fields": fields, "errorPolicy": "Omit"},
        )
        for item in data.get("value") or []:
            if item:
                result[item["id"]] = item["fields"]
    return result


def list_epics(ctx: BoardContext, active_columns: list[str]) -> list[dict]:
    """Épicos nas áreas do time e nas colunas ativas do board, mais recentes primeiro.
    Sem colunas configuradas, retorna todos exceto Removed."""
    _, areas = team_area_paths(ctx)
    area_clause = " OR ".join(
        f"[System.AreaPath] {'UNDER' if children else '='} {_wiql_literal(path)}" for path, children in areas
    )
    query = (
        "SELECT [System.Id] FROM WorkItems "
        "WHERE [System.WorkItemType] = 'Epic' AND [System.State] <> 'Removed' "
        f"AND ({area_clause}) ORDER BY [System.ChangedDate] DESC"
    )
    data = _request("POST", f"{_project_base(ctx)}/_apis/wit/wiql?api-version={API_VERSION}&$top=600", {"query": query})
    ids = [row["id"] for row in data.get("workItems", [])]
    fields = _batch_fields(ctx, ids, ["System.Title", "System.State", "System.BoardColumn"])
    allowed = set(active_columns)
    epics = []
    for epic_id in ids:  # preserva a ordem do WIQL
        f = fields.get(epic_id)
        if f is None:
            continue
        column = f.get("System.BoardColumn", "")
        if allowed and column not in allowed:
            continue
        epics.append({
            "id": epic_id,
            "title": f.get("System.Title", ""),
            "state": f.get("System.State", ""),
            "column": column,
            "url": work_item_url(ctx, epic_id),
        })
    return epics


def list_children(ctx: BoardContext, parent_id: int) -> list[dict]:
    """Filhos diretos (Hierarchy-Forward) de um work item."""
    item = _get(f"{_project_base(ctx)}/_apis/wit/workitems/{int(parent_id)}?$expand=relations&api-version={API_VERSION}")
    child_ids = [
        int(r["url"].rstrip("/").rsplit("/", 1)[1])
        for r in item.get("relations") or []
        if r.get("rel") == "System.LinkTypes.Hierarchy-Forward"
    ]
    fields = _batch_fields(ctx, child_ids, ["System.Title", "System.State", "System.WorkItemType"])
    return [
        {
            "id": cid,
            "title": fields[cid].get("System.Title", ""),
            "state": fields[cid].get("System.State", ""),
            "type": fields[cid].get("System.WorkItemType", ""),
            "url": work_item_url(ctx, cid),
        }
        for cid in child_ids
        if cid in fields
    ]


def get_work_item(ctx: BoardContext, work_item_id: int) -> dict:
    """Work item com todos os campos e relações."""
    return _get(f"{_project_base(ctx)}/_apis/wit/workitems/{int(work_item_id)}?$expand=all&api-version={API_VERSION}")


def search_work_items(ctx: BoardContext, text: str, limit: int = 15) -> list[dict]:
    """Busca por título (contains) no projeto, excluindo Removed. Mais recentes primeiro."""
    query = (
        "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
        f"AND [System.Title] CONTAINS {_wiql_literal(text)} AND [System.State] <> 'Removed' "
        "ORDER BY [System.ChangedDate] DESC"
    )
    data = _request("POST", f"{_project_base(ctx)}/_apis/wit/wiql?api-version={API_VERSION}&$top={int(limit)}", {"query": query})
    ids = [row["id"] for row in data.get("workItems", [])]
    fields = _batch_fields(ctx, ids, ["System.Title", "System.State", "System.WorkItemType"])
    return [
        {"id": i, "title": fields[i].get("System.Title", ""), "state": fields[i].get("System.State", ""),
         "type": fields[i].get("System.WorkItemType", ""), "url": work_item_url(ctx, i)}
        for i in ids if i in fields
    ]


# ---------- Wiki (somente leitura, confinada à página raiz configurada) ----------

MAX_WIKI_PAGES = 400   # teto de páginas percorridas na busca por título (fallback)
_WIKI_ROOT_CACHE: dict[tuple, str] = {}


def _wiki_base(wiki: WikiContext) -> str:
    return f"{wiki.org_url}/{_quote(wiki.project)}/_apis/wiki/wikis/{_quote(wiki.wiki)}"


def wiki_root_path(wiki: WikiContext) -> str:
    """Caminho da página raiz configurada (resolvido pelo id da página; sem id, a wiki inteira)."""
    if not wiki.page_id:
        return "/"
    key = (wiki.org_url, wiki.project, wiki.wiki, wiki.page_id)
    if key not in _WIKI_ROOT_CACHE:
        data = _get(f"{_wiki_base(wiki)}/pages/{wiki.page_id}?api-version={API_VERSION}")
        _WIKI_ROOT_CACHE[key] = data.get("path") or "/"
    return _WIKI_ROOT_CACHE[key]


def _wiki_abs(wiki: WikiContext, relative: str) -> str:
    """Caminho relativo à raiz -> caminho absoluto na wiki. Recusa '..' (não sai da raiz)."""
    parts = [p for p in (relative or "").replace("\\", "/").split("/") if p and p != "."]
    if ".." in parts:
        raise AzureError("Caminho fora da página raiz da wiki.")
    root = wiki_root_path(wiki).rstrip("/")
    return "/".join([root, *parts]) or "/"


def _wiki_relative(wiki: WikiContext, absolute: str) -> str:
    root = wiki_root_path(wiki).rstrip("/")
    return absolute[len(root):].lstrip("/") if root and absolute.startswith(root) else absolute.lstrip("/")


def _flatten_pages(wiki: WikiContext, page: dict, out: list[str]) -> None:
    for sub in page.get("subPages") or []:
        out.append(_wiki_relative(wiki, sub["path"]))
        _flatten_pages(wiki, sub, out)


def wiki_list_pages(wiki: WikiContext, relative: str = "", full: bool = False) -> list[str]:
    """Páginas abaixo de `relative` (caminhos relativos à raiz): filhas diretas, ou toda a árvore com full."""
    level = "full" if full else "oneLevel"
    data = _get(f"{_wiki_base(wiki)}/pages?path={_quote(_wiki_abs(wiki, relative))}"
                f"&recursionLevel={level}&api-version={API_VERSION}")
    pages: list[str] = []
    _flatten_pages(wiki, data, pages)
    return pages


def wiki_get_page(wiki: WikiContext, relative: str = "") -> str:
    """Conteúdo (markdown) da página."""
    data = _get(f"{_wiki_base(wiki)}/pages?path={_quote(_wiki_abs(wiki, relative))}"
                f"&includeContent=true&api-version={API_VERSION}")
    return data.get("content") or ""


def _plain(text: str) -> str:
    """Minúsculas e sem acentos, para a busca por título."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def wiki_search(wiki: WikiContext, text: str, limit: int = 10) -> list[str]:
    """Páginas sob a raiz cujo caminho contém todas as palavras do texto (sem acento, sem diferenciar
    maiúsculas). É busca por título/caminho: o serviço de busca do Azure DevOps varre a wiki inteira e
    devolve caminhos de arquivo que não se ligam com segurança à raiz configurada."""
    words = _plain(text).split()
    if not words:
        return []
    pages = wiki_list_pages(wiki, "", full=True)[:MAX_WIKI_PAGES]
    return [p for p in pages if all(w in _plain(p) for w in words)][:limit]


# ---------- Campos e criação de cards ----------

_FIELD_CACHE: dict[tuple, dict[str, str]] = {}


def type_fields(ctx: BoardContext, work_item_type: str) -> dict[str, str]:
    """Mapa nome de exibição -> nome de referência dos campos do tipo de work item."""
    key = (ctx.org_url, ctx.project, work_item_type)
    if key not in _FIELD_CACHE:
        data = _get(f"{_project_base(ctx)}/_apis/wit/workitemtypes/{_quote(work_item_type)}/fields?api-version={API_VERSION}")
        _FIELD_CACHE[key] = {f["name"]: f["referenceName"] for f in data.get("value", [])}
    return _FIELD_CACHE[key]


_FIELD_TYPE_CACHE: dict[tuple, str] = {}


def field_type(ctx: BoardContext, reference_name: str) -> str:
    """Tipo de dados do campo no Azure DevOps (html, plainText, string...). Desconhecido => 'html'."""
    key = (ctx.org_url, ctx.project, reference_name)
    if key not in _FIELD_TYPE_CACHE:
        try:
            data = _get(f"{_project_base(ctx)}/_apis/wit/fields/{_quote(reference_name)}?api-version={API_VERSION}")
            _FIELD_TYPE_CACHE[key] = data.get("type") or "html"
        except AzureError:
            return "html"
    return _FIELD_TYPE_CACHE[key]


_LAYOUT_CACHE: dict[tuple, dict[str, str]] = {}


def type_layout_labels(ctx: BoardContext, work_item_type: str) -> dict[str, str]:
    """Rótulos exibidos no formulário do card -> nome de referência do campo.

    O rótulo do formulário pode diferir do nome do campo (ex.: o rótulo 'Critérios de Aceite' é o
    campo 'Acceptance Criteria'). Usa a API de processos; se o PAT não tiver acesso, devolve vazio."""
    key = (ctx.org_url, ctx.project, work_item_type)
    if key in _LAYOUT_CACHE:
        return _LAYOUT_CACHE[key]
    labels: dict[str, str] = {}
    try:
        project = _get(f"{ctx.org_url}/_apis/projects/{_quote(ctx.project)}?includeCapabilities=true&api-version={API_VERSION}")
        process_id = project["capabilities"]["processTemplate"]["templateTypeId"]
        types = _get(f"{ctx.org_url}/_apis/work/processes/{process_id}/workitemtypes?api-version={API_VERSION}")["value"]
        type_ref = next(t["referenceName"] for t in types if t["name"].casefold() == work_item_type.casefold())
        layout = _get(f"{ctx.org_url}/_apis/work/processes/{process_id}/workItemTypes/{type_ref}/layout?api-version={API_VERSION}")
        for page in layout.get("pages", []):
            for section in page.get("sections", []):
                for group in section.get("groups", []):
                    for control in group.get("controls", []):
                        if control.get("id") and control.get("label"):
                            labels.setdefault(control["label"].casefold(), control["id"])
    except (AzureError, KeyError, StopIteration):
        labels = {}
    _LAYOUT_CACHE[key] = labels
    return labels


def resolve_field_refs(
    ctx: BoardContext, work_item_type: str, display_names: dict[str, str | list[str]]
) -> tuple[dict[str, str], list[str]]:
    """{chave_lógica: nome ou lista de nomes} -> ({chave_lógica: nome_de_referência}, [chaves não encontradas]).

    O nome configurado é procurado, nesta ordem, entre: rótulos do formulário, nomes dos campos e
    nomes de referência. Campos que o tipo não possui ficam em `missing` (ex.: Spike não tem
    'Repositórios Alterados'); quem chama decide como tratar."""
    labels = {_norm(label): ref for label, ref in type_layout_labels(ctx, work_item_type).items()}
    fields = type_fields(ctx, work_item_type)
    by_name = {_norm(name): ref for name, ref in fields.items()}
    known_refs = set(fields.values())
    resolved, missing = {}, []
    for key, configured in display_names.items():
        candidates = [configured] if isinstance(configured, str) else list(configured)
        ref = next(
            (r for c in candidates
             for r in (labels.get(_norm(c)), by_name.get(_norm(c)), c if c in known_refs else None)
             if r in known_refs),
            None,
        )
        if ref is None:
            missing.append(key)
        else:
            resolved[key] = ref
    return resolved, missing


def _norm(text: str) -> str:
    """Ignora caixa e espaços repetidos (o campo 'Recursos  impactados' tem dois espaços)."""
    return " ".join(text.split()).casefold()


def build_create_patch(
    ctx: BoardContext,
    title: str,
    area_path: str,
    fields: dict[str, str],
    parent_id: int | None,
    related_ids: list[int],
) -> list[dict]:
    """Documento JSON Patch para criar o card. `fields` mapeia nome de referência -> HTML."""
    ops = [
        {"op": "add", "path": "/fields/System.Title", "value": title},
        {"op": "add", "path": "/fields/System.AreaPath", "value": area_path},
    ]
    for ref, html in fields.items():
        if html:
            ops.append({"op": "add", "path": f"/fields/{ref}", "value": html})

    def link(rel: str, target: int) -> dict:
        return {
            "op": "add",
            "path": "/relations/-",
            "value": {"rel": rel, "url": f"{_project_base(ctx)}/_apis/wit/workItems/{target}"},
        }

    if parent_id:
        ops.append(link("System.LinkTypes.Hierarchy-Reverse", parent_id))
    for related in dict.fromkeys(related_ids):  # sem duplicados, mantém a ordem
        if related != parent_id:
            ops.append(link("System.LinkTypes.Related", related))
    return ops


def create_work_item(ctx: BoardContext, work_item_type: str, patch: list[dict]) -> dict:
    """Cria o work item. Retorna {id, url}."""
    data = _request(
        "POST",
        f"{_project_base(ctx)}/_apis/wit/workitems/${_quote(work_item_type)}?api-version={API_VERSION}",
        patch,
        content_type="application/json-patch+json",
    )
    return {"id": data["id"], "url": work_item_url(ctx, data["id"])}
