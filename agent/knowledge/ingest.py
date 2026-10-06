"""Ingestão assistida da ontologia: lê a wiki (e o Notion), extrai conceitos com o modelo e grava RASCUNHOS.

Princípios:
- Só roda quando o usuário pede, com ensaio antes (contagens e custo estimado, sem chamar o modelo).
- Leitura educada: UM download (zip da subárvore da raiz configurada, com teto de tamanho) em vez de
  centenas de requisições; sem zip, página a página com intervalo, Retry-After e parada em 401/403.
- Incremental: guarda o commit da raiz e o hash de cada página; nada mudou = nenhuma leitura de conteúdo.
- Só escreve em `_rascunhos/` da pasta da ontologia. NUNCA sobrescreve nota validada nem rascunho editado à mão.
- Páginas com segredos são puladas; o texto das descrições passa pelo verificador STE-pt (1 reescrita)."""
import hashlib
import io
import json
import os
import re
import time
import zipfile
from datetime import date, datetime
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import quote, unquote

from agent import generation
from agent.knowledge import style
from agent.knowledge.secrets import find_secrets
from agent.knowledge.store import DRAFTS_DIR, OntologyStore, dump_note, parse_frontmatter
from integrations import azure_client as az
from integrations.polite import PoliteClient, PoliteStop
from integrations.wiki_url import InvalidWikiUrl, parse_wiki_url

ROOT = Path(__file__).resolve().parent.parent.parent
STATE_PATH = Path(os.environ.get("STORIES_ONTOLOGY_STATE") or ROOT / "storage" / "ontology-state.json")
LOG_PATH = Path(os.environ.get("STORIES_ONTOLOGY_LOG") or ROOT / "storage" / "ontology-ingest.log")
STE_RULES = (Path(__file__).parent / "ste_pt.md").read_text(encoding="utf-8")

KINDS = ("conceito", "sistema", "repositorio", "fluxo", "regra")
MAX_ZIP_BYTES = 60 * 1024 * 1024
MAX_PAGE_BYTES = 200_000
MAX_PAGE_CHARS = 12_000            # o que da página vai ao modelo
MIN_PAGE_CHARS = 200
MAX_CONCEPTS_PER_PAGE = 8
MAX_DESC_CHARS = 700
MAX_CONSECUTIVE_ERRORS = 5
CHARS_PER_TOKEN = 3.5
OUTPUT_TOKENS_PER_PAGE = 700
FETCH_TTL = 1800

EXTRACTION_SYSTEM = """Você extrai conhecimento de domínio (Cobrança, Bemol Serviços Financeiros) de UMA página de \
documentação, para montar uma ontologia. Responda SOMENTE um objeto JSON, sem cercas de código:
{"conceitos": [{"nome": "...", "tipo": "conceito|sistema|repositorio|fluxo|regra", "sinonimos": ["..."], \
"descricao": "...", "relacoes": [{"rel": "...", "alvo": "Nome de outro conceito"}]}]}

Regras:
- No máximo 8 conceitos. Registre só o que a página afirma. Nunca invente nem complete com conhecimento próprio.
- Se a página não tem conhecimento de domínio útil (ata, lista de tarefas, convite, agenda), devolva {"conceitos": []}.
- "nome": o termo mais usado, no singular e o mais curto possível. Siglas e variações vão em "sinonimos".
- "tipo": conceito (ideia do negócio), sistema (aplicação/serviço/API), repositorio (código), fluxo (sequência de \
passos), regra (condição de negócio).
- "relacoes": verbo curto em snake_case (usa, chama, chamado_por, gera, parte_de, depende_de, executada_por, \
regida_por, substitui). O alvo é o nome de outro conceito.
- Nunca copie senhas, tokens, chaves, endereços de e-mail nem dados pessoais.

""" + STE_RULES

_FETCH_CACHE: dict = {}


class IngestError(RuntimeError):
    pass


# ---------- estado e log ----------

def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def log(message: str) -> None:
    """Trilha de auditoria local: só contagens, códigos e caminhos; nunca o conteúdo das páginas."""
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# ---------- caminhos: página da wiki <-> caminho no git ----------

def git_path(page_path: str) -> str:
    """'/A B/C-D' -> '/A-B/C%2DD' (a wiki guarda espaço como '-' e '-' como '%2D')."""
    return "/" + "/".join(seg.replace("-", "%2D").replace(" ", "-") for seg in page_path.split("/") if seg)


def page_from_git(rel: str) -> str:
    """Inverso, por segmento: 'A-B/C%2DD.md' -> 'A B/C-D'."""
    rel = rel[:-3] if rel.lower().endswith(".md") else rel
    return "/".join(unquote(seg.replace("-", " ")) for seg in rel.split("/") if seg)


def _excluded(page: str, patterns: list[str]) -> bool:
    folded = style.fold(page)
    return any(fnmatch(folded, style.fold(p)) or style.fold(p) in folded for p in patterns)


# ---------- leitura da wiki ----------

def _flatten(page: dict, out: list[str]) -> None:
    for sub in page.get("subPages") or []:
        out.append(sub["path"])
        _flatten(sub, out)


def fetch_wiki(wiki, client: PoliteClient, exclude: list[str], max_pages: int, force: bool = False) -> dict:
    """{"commit", "pages": {relativo: texto}, "via", "unchanged"}. Cache em memória evita baixar duas vezes
    (ensaio e execução)."""
    base = az._wiki_base(wiki)
    info = client.get_json(f"{base}?api-version={az.API_VERSION}")
    repo = info["repositoryId"]
    root = az.wiki_root_path(wiki)
    scope = git_path(root)
    org_proj = f"{wiki.org_url}/{quote(wiki.project, safe='')}"

    commits = client.get_json(f"{org_proj}/_apis/git/repositories/{repo}/commits?searchCriteria.itemPath="
                              f"{quote(scope, safe='')}&searchCriteria.$top=1&api-version={az.API_VERSION}")
    commit = (commits.get("value") or [{}])[0].get("commitId", "")
    key = (wiki.org_url, wiki.project, wiki.wiki, root, commit)
    cached = _FETCH_CACHE.get("fetch")
    if cached and cached["key"] == key and time.time() - cached["at"] < FETCH_TTL:
        return {**cached["data"], "requests": 0}
    if commit and commit == load_state().get("wiki", {}).get("commit") and not force:
        return {"commit": commit, "pages": {}, "via": "estado", "unchanged": True}

    pages: dict[str, str] = {}
    via = "zip"
    try:
        url = (f"{org_proj}/_apis/git/repositories/{repo}/items?scopePath={quote(scope, safe='')}"
               f"&recursionLevel=full&$format=zip&download=true&api-version={az.API_VERSION}")
        data, _ = client.get(url, accept="application/zip", max_bytes=MAX_ZIP_BYTES)
        # O zip da subárvore traz a própria pasta raiz como diretório de topo (confirmado no Azure DevOps);
        # aceita também o caminho completo do repositório ou nomes já relativos.
        prefixes = [scope.lstrip("/") + "/", scope.rstrip("/").rsplit("/", 1)[-1] + "/"]
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if not name.lower().endswith(".md") or any(p.startswith(".") for p in name.split("/")):
                    continue
                info_ = z.getinfo(name)
                if info_.file_size > MAX_PAGE_BYTES:
                    continue
                rel = next((name[len(p):] for p in prefixes if name.startswith(p)), name)
                pages[page_from_git(rel)] = z.read(name).decode("utf-8", errors="replace")
        # a página raiz é um arquivo ao lado da pasta (ex.: '<raiz>.md')
        try:
            top, _ = client.get(f"{org_proj}/_apis/git/repositories/{repo}/items?path={quote(scope + '.md', safe='')}"
                                f"&download=true&api-version={az.API_VERSION}", accept="text/plain", max_bytes=MAX_PAGE_BYTES)
            pages.setdefault("(raiz)", top.decode("utf-8", errors="replace"))
        except az.AzureError as err:
            if isinstance(err, PoliteStop) and err.status in (401, 429, 503):
                raise
    except PoliteStop as err:
        if err.status != 403:     # 403 no zip pode ser só falta de escopo de código: tenta página a página
            raise
        via = "paginas"
        pages = _fetch_page_by_page(wiki, client, root, max_pages)

    pages = {p: t for p, t in pages.items() if not _excluded(p, exclude)}
    result = {"commit": commit, "pages": pages, "via": via, "unchanged": False, "requests": client.requests}
    _FETCH_CACHE["fetch"] = {"key": key, "at": time.time(), "data": result}
    return result


def _fetch_page_by_page(wiki, client: PoliteClient, root: str, max_pages: int) -> dict[str, str]:
    base = az._wiki_base(wiki)
    tree = client.get_json(f"{base}/pages?path={quote(root, safe='')}&recursionLevel=full&api-version={az.API_VERSION}")
    paths: list[str] = []
    _flatten(tree, paths)
    out: dict[str, str] = {}
    for absolute in paths[:max_pages]:
        data = client.get_json(f"{base}/pages?path={quote(absolute, safe='')}&includeContent=true&api-version={az.API_VERSION}")
        content = data.get("content") or ""
        if len(content) <= MAX_PAGE_BYTES:
            out[az._wiki_relative(wiki, absolute)] = content
    return out


# ---------- extração com o modelo ----------

def chat_with_retry(llm, messages: list, sleep=time.sleep, attempts: int = 4):
    """Uma chamada ao modelo com recuo em 429 (respeita Retry-After). Outros erros sobem."""
    for attempt in range(1, attempts + 1):
        try:
            return llm.chat(messages, [])
        except Exception as err:  # noqa: BLE001
            if getattr(err, "status_code", None) != 429 or attempt == attempts:
                raise
            headers = getattr(getattr(err, "response", None), "headers", None) or {}
            try:
                wait = float(headers.get("retry-after"))
            except (TypeError, ValueError):
                wait = 2.0 ** attempt
            sleep(min(wait, 60.0))


def _clean_name(name) -> str:
    name = re.sub(r'[\\/:*?"<>|\[\]#^]', " ", str(name or ""))
    return " ".join(name.split())[:80].strip(" .")


def _synonyms(name: str, raw) -> list[str]:
    """Sinônimos limpos: sem nomes de arquivo/caminho, sem repetir o próprio nome, sem duplicatas."""
    out: dict[str, str] = {}
    for item in (raw or [])[:10] if isinstance(raw, list) else []:
        text = " ".join(str(item).replace("\\", "/").split())
        if not text or "/" in text or text.lower().endswith(".md") or len(text) > 60:
            continue
        key = style.fold(text)
        if key != style.fold(name):
            out.setdefault(key, text)
    return list(out.values())


def normalize_concepts(data: dict) -> list[dict]:
    out = []
    for raw in (data.get("conceitos") or [])[:MAX_CONCEPTS_PER_PAGE]:
        if not isinstance(raw, dict):
            continue
        name = _clean_name(raw.get("nome"))
        name = name[:1].upper() + name[1:]          # nome de nota começa em maiúscula ("ata" -> "Ata")
        description = " ".join(str(raw.get("descricao") or "").split())[:MAX_DESC_CHARS]
        if not name or not description:
            continue
        kind = str(raw.get("tipo") or "conceito").lower()
        relations = []
        for rel in (raw.get("relacoes") or [])[:10]:
            if isinstance(rel, dict) and _clean_name(rel.get("alvo")):
                verb = re.sub(r"[^a-z_]", "", str(rel.get("rel") or "relacionado").lower().replace(" ", "_")) or "relacionado"
                relations.append({"rel": verb, "alvo": _clean_name(rel["alvo"])})
        out.append({
            "nome": name, "tipo": kind if kind in KINDS else "conceito", "descricao": description,
            "fonte": str(raw.get("fonte") or "").strip()[:200],
            "sinonimos": _synonyms(name, raw.get("sinonimos")),
            "relacoes": relations,
        })
    return out


def extract_page(llm, path: str, text: str, sleep=time.sleep) -> list[dict]:
    messages = [{"role": "system", "content": EXTRACTION_SYSTEM},
                {"role": "user", "content": f"Página: {path}\n\n{text[:MAX_PAGE_CHARS]}"}]
    reply = chat_with_retry(llm, messages, sleep).content or ""
    try:
        return normalize_concepts(generation._extract_json(reply))
    except (ValueError, json.JSONDecodeError):
        reply = chat_with_retry(llm, [*messages, {"role": "assistant", "content": reply}, {"role": "user", "content":
                                "Resposta ilegível. Reenvie SOMENTE o objeto JSON no formato exigido."}], sleep).content or ""
        return normalize_concepts(generation._extract_json(reply))


def enforce_style(llm, store: OntologyStore, concept: dict, sleep=time.sleep) -> list[str]:
    """Verifica o padrão STE-pt; se houver avisos, UMA reescrita. Devolve os avisos que restaram."""
    unapproved, known = store.unapproved_terms(), store.known_acronyms()
    warnings = style.check(concept["descricao"], unapproved, known)
    if not warnings:
        return []
    prompt = (f"Reescreva a descrição do conceito «{concept['nome']}» no padrão STE-pt, sem mudar os fatos e sem "
              "acrescentar nada. Corrija estas violações:\n" + "\n".join(f"- {w}" for w in warnings) +
              f"\n\nTexto:\n{concept['descricao']}\n\nResponda SOMENTE o texto reescrito.")
    rewritten = " ".join((chat_with_retry(llm, [{"role": "system", "content": STE_RULES}, {"role": "user", "content": prompt}],
                                          sleep).content or "").split())[:MAX_DESC_CHARS]
    if rewritten:
        concept["descricao"] = rewritten
    return style.check(concept["descricao"], unapproved, known)


# ---------- gravação de rascunhos ----------

def write_draft(root: Path, store: OntologyStore, concept: dict, source: str, written: dict, warnings: list[str]) -> str:
    """Grava ou funde um rascunho. Devolve a ação: criado | fundido | atualizacao | sem mudança | preservado."""
    name = concept["nome"]
    existing = store.resolve(name)
    meta = {"tipo": concept["tipo"], "sinonimos": concept["sinonimos"], "relacoes": concept["relacoes"],
            "fontes": [source], "status": "rascunho", "atualizado": date.today().isoformat(), "origem": "ia"}
    description = concept["descricao"]
    action = "criado"
    if existing is not None and not existing.is_draft:
        if style.fold(existing.body) == style.fold(description):
            return "sem mudança"
        meta["atualiza"] = f"[[{existing.name}]]"
        action = "atualizacao"
        target = root / DRAFTS_DIR / concept["tipo"] / f"{name}.md"
        if target.exists():
            # O arquivo já existe: ou é a própria nota promovida (validada no lugar) ou uma proposta anterior.
            # Só reescreve se for proposta nossa, intacta; nunca a nota validada nem uma edição manual.
            rel = target.relative_to(root).as_posix()
            if written.get(rel) != _sha(target.read_text(encoding="utf-8")) or target == root / existing.path:
                return "preservado"
    elif existing is not None:
        target = root / existing.path
        old = target.read_text(encoding="utf-8")
        rel = target.relative_to(root).as_posix()
        if written.get(rel) != _sha(old):          # o usuário mexeu no rascunho: não toca
            return "preservado"
        old_meta, old_body = parse_frontmatter(old)
        for key in ("sinonimos", "fontes"):
            meta[key] = list(dict.fromkeys([*[str(x) for x in old_meta.get(key, []) or []], *meta[key]]))
        have = {(r.get("rel"), r.get("alvo", "").strip("[]")) for r in old_meta.get("relacoes", []) or [] if isinstance(r, dict)}
        meta["relacoes"] = [{"rel": r["rel"], "alvo": r["alvo"].strip("[]")} for r in old_meta.get("relacoes", []) or []
                            if isinstance(r, dict)] + [r for r in meta["relacoes"] if (r["rel"], r["alvo"]) not in have]
        description = old_body or description
        action = "fundido"
    else:
        target = root / DRAFTS_DIR / concept["tipo"] / f"{name}.md"

    if style.check(description, store.unapproved_terms(), store.known_acronyms()) or warnings:
        meta["ste_avisos"] = (warnings or style.check(description, store.unapproved_terms(), store.known_acronyms()))[:6]
    content = dump_note(meta, description)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    written[target.relative_to(root).as_posix()] = _sha(content)
    return action


# ---------- orquestração ----------

def estimate_tokens(pages: dict[str, str]) -> int:
    return int(sum(min(len(t), MAX_PAGE_CHARS) / CHARS_PER_TOKEN + OUTPUT_TOKENS_PER_PAGE for t in pages.values()))


def run_ingest(llm, settings: dict, *, dry_run: bool = True, limit: int | None = None, force: bool = False,
               include_notion: bool = False, on_step=None, client: PoliteClient | None = None,
               sleep=time.sleep) -> dict:
    cfg = settings.get("ontology", {})
    folder = (cfg.get("dir") or "").strip()
    if not folder:
        raise IngestError("Configure a pasta da ontologia em ⚙️ antes de construir.")
    root = Path(folder) if Path(folder).is_absolute() else ROOT / folder
    step = on_step or (lambda s: None)
    summary = {"dry_run": dry_run, "wiki": None, "notion": None, "drafts": {}, "errors": [], "skipped_secrets": [],
               "stopped": "", "requests": 0}

    try:
        wiki = parse_wiki_url(settings["azure"].get("wiki_url", ""))
    except InvalidWikiUrl:
        wiki = None
    if wiki is None and not include_notion:
        raise IngestError("Configure a URL da wiki em ⚙️ (ou habilite o Notion) para construir a ontologia.")

    if wiki is not None:
        client = client or PoliteClient(sleep=sleep)
        step({"message": "Consultando a wiki (um download da subárvore da raiz)..."})
        try:
            fetched = fetch_wiki(wiki, client, cfg.get("ingest_exclude") or [], int(cfg.get("ingest_max_pages", 150)), force)
        except az.AzureError as err:
            log(f"wiki ERRO status={getattr(err, 'status', None)} requisicoes={client.requests}")
            raise IngestError(str(err)) from err
        state = load_state()
        known = state.get("wiki", {}).get("pages", {})
        pages = fetched["pages"]
        changed = sorted(p for p, t in pages.items() if known.get(p) != _sha(t) and len(t.strip()) >= MIN_PAGE_CHARS)
        secret_pages = sorted(p for p in changed if find_secrets(pages[p]))
        todo = [p for p in changed if p not in secret_pages]
        cap = min(int(cfg.get("ingest_max_pages", 150)), limit or 10 ** 9)
        capped = len(todo) > cap
        todo = todo[:cap]
        summary["wiki"] = {"commit": fetched["commit"][:10], "via": fetched["via"], "sem_mudancas": fetched["unchanged"],
                           "paginas_na_raiz": len(pages), "paginas_a_processar": len(todo), "limitado_pelo_teto": capped,
                           "puladas_por_segredo": len(secret_pages),
                           "tokens_estimados": estimate_tokens({p: pages[p] for p in todo})}
        summary["skipped_secrets"] = secret_pages
        summary["requests"] = client.requests
        log(f"wiki dry_run={dry_run} via={fetched['via']} requisicoes={client.requests} paginas={len(pages)} "
            f"a_processar={len(todo)} segredos={len(secret_pages)}")

        if not dry_run and (todo or secret_pages):
            _process_pages(llm, root, wiki, fetched, todo, secret_pages, cfg, state, summary, step, sleep)
        summary["requests"] = client.requests

    if include_notion and not dry_run:
        from . import notion_ingest
        summary["notion"] = notion_ingest.run(llm, settings, root, step, sleep, summary)
    elif include_notion:
        summary["notion"] = {"observacao": "O Notion é lido por uma execução do agente (até alguns passos); sem estimativa exata."}
    return summary


def _process_pages(llm, root, wiki, fetched, todo, secret_pages, cfg, state, summary, step, sleep) -> None:
    store = OntologyStore(root)
    pages = fetched["pages"]
    wiki_state = state.setdefault("wiki", {}).setdefault("pages", {})
    written = state.setdefault("drafts", {})
    budget = int(cfg.get("ingest_max_tokens", 300_000))
    spent, errors_in_a_row = 0, 0
    counts = {"criado": 0, "fundido": 0, "atualizacao": 0, "sem mudança": 0, "preservado": 0}
    done_all = True

    for i, page in enumerate(todo, 1):
        cost = estimate_tokens({page: pages[page]})
        if spent + cost > budget:
            summary["stopped"] = f"orçamento de {budget} tokens atingido; rode de novo para continuar"
            done_all = False
            break
        step({"message": f"Página {i}/{len(todo)}: {page}", "done": i - 1, "total": len(todo)})
        try:
            concepts = extract_page(llm, page, pages[page], sleep)
            for concept in concepts:
                warnings = enforce_style(llm, store, concept, sleep)
                action = write_draft(root, store, concept, f"wiki:/{page}", written, warnings)
                counts[action] = counts.get(action, 0) + 1
            errors_in_a_row = 0
        except Exception as err:  # noqa: BLE001 - uma página ruim não derruba a execução
            errors_in_a_row += 1
            summary["errors"].append(f"{page}: {type(err).__name__}: {str(err)[:120]}")
            if errors_in_a_row >= MAX_CONSECUTIVE_ERRORS:
                summary["stopped"] = f"{MAX_CONSECUTIVE_ERRORS} erros seguidos; execução interrompida"
                done_all = False
                break
            continue
        spent += cost
        wiki_state[page] = _sha(pages[page])
        save_state(state)
        sleep(0.3)

    for page in secret_pages:                      # tratadas de propósito: só voltam se o conteúdo mudar
        wiki_state[page] = _sha(pages[page])
    summary["drafts"] = counts
    summary["tokens_estimados_gastos"] = spent
    # O commit só é gravado quando NADA ficou pendente (teto, orçamento ou erro); senão a próxima execução
    # continua pelo hash das páginas.
    pending = [p for p, t in pages.items() if wiki_state.get(p) != _sha(t) and len(t.strip()) >= MIN_PAGE_CHARS]
    if done_all and not pending and not summary["errors"]:
        state.setdefault("wiki", {})["commit"] = fetched["commit"]
    save_state(state)
    log(f"wiki processadas={len(todo)} drafts={counts} erros={len(summary['errors'])} parada='{summary['stopped']}'")
