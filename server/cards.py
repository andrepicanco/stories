"""Criação do card no Azure DevOps a partir do conteúdo da tela.

`prepare` valida tudo e monta o payload SEM enviar (também usado no modo ensaio); `create` envia."""
from dataclasses import dataclass, field

from integrations import azure_client
from integrations.board_url import BoardContext
from integrations.html_sanitize import sanitize_html
from integrations.html_text import html_to_text

DEFAULT_TITLE = "Nova História"
MAX_TITLE = 255
PLAIN_TEXT_TYPES = {"plainText", "string"}


class CardError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


@dataclass
class CardRequest:
    card_type: str
    epic_id: int | None
    related: list[int]
    title: str
    card_html: str
    resources_html: str = ""
    criteria_html: str = ""


@dataclass
class Prepared:
    work_item_type: str
    title: str
    patch: list[dict]
    warnings: list[str] = field(default_factory=list)


def prepare(ctx: BoardContext, settings: dict, req: CardRequest, azure=azure_client) -> Prepared:
    cfg = settings["azure"]
    title = " ".join(req.title.split())
    if not title or title == DEFAULT_TITLE:
        raise CardError("Defina o título do card (ele ainda está com o nome padrão).")
    if len(title) > MAX_TITLE:
        raise CardError(f"O título tem {len(title)} caracteres; o limite do Azure DevOps é {MAX_TITLE}.")

    wit = cfg["work_item_types"].get(req.card_type)
    if not wit:
        raise CardError(f"Tipo de card inválido: {req.card_type}")
    card_html = sanitize_html(req.card_html)
    if not card_html:
        raise CardError("O “Texto do card” está vazio.")
    if not req.epic_id:
        raise CardError("Selecione o Épico: o card é criado como filho dele.")

    related = list(dict.fromkeys(req.related))
    if related:
        child_ids = {c["id"] for c in azure.list_children(ctx, req.epic_id)}
        strangers = [r for r in related if r not in child_ids]
        if strangers:
            raise CardError("Cards relacionados precisam ser filhos do épico selecionado: "
                            + ", ".join(f"#{r}" for r in strangers))

    refs, missing = azure.resolve_field_refs(ctx, wit, cfg["fields"])
    if "description" in missing:
        raise CardError(f"O tipo '{wit}' não tem o campo de descrição configurado. Confira as configurações.")

    warnings: list[str] = []
    description = card_html
    criteria = sanitize_html(req.criteria_html)
    resources = sanitize_html(req.resources_html)
    # Campos que o tipo não possui (ex.: Spike sem "Repositórios Alterados") vão para o fim da descrição.
    if criteria and "acceptance_criteria" in missing:
        description += f"<h2>Critérios de Aceite</h2>{criteria}"
        criteria = ""
        warnings.append(f"O tipo '{wit}' não tem campo de critérios de aceite: o conteúdo foi anexado à descrição.")
    if resources and "impacted_resources" in missing:
        description += f"<h2>Recursos impactados</h2>{resources}"
        resources = ""
        warnings.append(f"O tipo '{wit}' não tem campo de recursos impactados: o conteúdo foi anexado à descrição.")

    values = {refs["description"]: description}
    if criteria:
        values[refs["acceptance_criteria"]] = criteria
    if resources:
        values[refs["impacted_resources"]] = resources
    for ref in list(values):                      # campo de texto puro não entende HTML
        if azure.field_type(ctx, ref) in PLAIN_TEXT_TYPES:
            values[ref] = html_to_text(values[ref])

    default_area, _ = azure.team_area_paths(ctx)
    patch = azure.build_create_patch(ctx, title, default_area, values, req.epic_id, related)
    return Prepared(work_item_type=wit, title=title, patch=patch, warnings=warnings)


def create(ctx: BoardContext, prepared: Prepared, azure=azure_client) -> dict:
    created = azure.create_work_item(ctx, prepared.work_item_type, prepared.patch)
    return {"id": created["id"], "url": created["url"], "title": prepared.title, "warnings": prepared.warnings}
