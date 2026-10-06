"""Ontologia de domínio: uma pasta de notas Markdown com frontmatter (conceitos, sistemas, fluxos, regras...).

- Notas fora de `_rascunhos/` são validadas (a menos que o frontmatter diga `status: rascunho`).
- Notas em `_rascunhos/` são propostas da IA e nunca contam como fato confirmado.
- `Eventos/AAAA-MM.md` guarda a cronologia: uma linha por evento, `- 2026-10-06 | card:288965 | texto | [[Nota]]`.
Tudo é lido de dentro da pasta configurada: nada fora dela, nada oculto."""
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import style

DRAFTS_DIR = "_rascunhos"
EVENTS_DIR = "Eventos"
MAX_NOTE_BYTES = 200_000
_WIKILINK = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|[^\]]*)?\]\]")
_EVENT = re.compile(r"^-\s+(\d{4}-\d{2}-\d{2})\s*\|\s*(.*)$")


# ---------- frontmatter (subconjunto mínimo de YAML) ----------

def _split_top(text: str) -> list[str]:
    """Divide por vírgulas fora de aspas e de colchetes/chaves."""
    parts, depth, quote, current = [], 0, "", []
    for ch in text:
        if quote:
            current.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            current.append(ch)
        elif ch in "[{":
            depth += 1
            current.append(ch)
        elif ch in "]}":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def _scalar(text: str) -> str:
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


def _value(text: str):
    text = text.strip()
    if text.startswith("{") and text.endswith("}"):
        out = {}
        for part in _split_top(text[1:-1]):
            key, _, val = part.partition(":")
            out[key.strip()] = _scalar(val)
        return out
    if text.startswith("[") and text.endswith("]") and not text.startswith("[["):
        return [_value(p) for p in _split_top(text[1:-1])]
    return _scalar(text)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """(metadados, corpo). Sem frontmatter válido, devolve ({}, texto)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}, text
    meta: dict = {}
    key = None
    for raw in lines[1:end]:
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        item = re.match(r"^\s+-\s+(.*)$", raw)
        if item and key:
            meta.setdefault(key, [])
            if isinstance(meta[key], list):
                meta[key].append(_value(item.group(1)))
            continue
        k, sep, v = raw.partition(":")
        if not sep:
            continue
        key = k.strip()
        meta[key] = _value(v) if v.strip() else []
    return meta, "\n".join(lines[end + 1:]).strip()


def _as_list(value) -> list:
    if value in (None, "", []):
        return []
    return value if isinstance(value, list) else [value]


def link_target(text: str) -> str:
    """'[[Sistemas/CRM|o CRM]]' -> 'CRM'; texto sem colchetes é devolvido como está."""
    m = _WIKILINK.search(text or "")
    name = m.group(1) if m else (text or "")
    return name.strip().split("/")[-1].strip()


def _quote(value) -> str:
    """Texto seguro para o frontmatter (o parser acima não trata escapes: aspas internas viram apóstrofos)."""
    return '"' + str(value).replace('"', "'").replace("\n", " ").strip() + '"'


def dump_note(meta: dict, body: str) -> str:
    """Inverso de parse_frontmatter para os campos da ontologia: tipo, sinonimos, relacoes, fontes, status, ..."""
    lines = ["---"]
    for key, value in meta.items():
        if value in (None, "", []):
            continue
        if key == "relacoes":
            lines.append("relacoes:")
            lines += [f"  - {{rel: {_quote(r['rel'])}, alvo: {_quote('[[' + r['alvo'] + ']]')}}}" for r in value]
        elif key in ("sinonimos", "fontes", "ste_avisos"):
            if key == "ste_avisos":
                lines.append("ste_avisos:")
                lines += [f"  - {_quote(v)}" for v in value]
            else:
                lines.append(f"{key}: [{', '.join(_quote(v) for v in value)}]")
        else:
            lines.append(f"{key}: {_quote(value) if ':' in str(value) or '[' in str(value) else value}")
    lines += ["---", "", body.strip(), ""]
    return "\n".join(lines)


# ---------- notas ----------

@dataclass
class Note:
    name: str
    kind: str
    synonyms: list[str]
    relations: list[tuple[str, str]]     # (relação, nome da nota alvo)
    sources: list[str]
    status: str                          # validado | rascunho
    updated: str
    body: str
    path: str                            # relativo à pasta da ontologia
    warnings: list[str] = field(default_factory=list)

    @property
    def is_draft(self) -> bool:
        return self.status != "validado"


class OntologyStore:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._cache: tuple | None = None
        self._notes: list[Note] = []

    # -- leitura --
    def _files(self):
        if not self.root.is_dir():
            return
        for path in sorted(self.root.rglob("*.md")):
            rel = path.relative_to(self.root)
            if any(p.startswith(".") for p in rel.parts) or rel.parts[0] == EVENTS_DIR:
                continue
            if path.is_file() and path.stat().st_size <= MAX_NOTE_BYTES:
                yield path, rel

    def notes(self) -> list[Note]:
        files = list(self._files())
        signature = tuple((str(p), p.stat().st_mtime_ns) for p, _ in files)
        if signature != self._cache:
            self._notes = [self._load(p, rel) for p, rel in files]
            self._cache = signature
            self._annotate()
        return self._notes

    @staticmethod
    def _load(path: Path, rel: Path) -> Note:
        meta, body = parse_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
        in_drafts = rel.parts[0] == DRAFTS_DIR
        # O `status` do frontmatter manda: promover = trocar para `validado`, em qualquer pasta. Sem `status`, uma nota
        # em _rascunhos/ é rascunho e as demais são validadas. Qualquer valor diferente de "validado" é rascunho.
        status = str(meta.get("status") or ("rascunho" if in_drafts else "validado")).strip().lower()
        relations = []
        for item in _as_list(meta.get("relacoes")):
            if isinstance(item, dict) and item.get("alvo"):
                relations.append((str(item.get("rel") or "relacionado"), link_target(str(item["alvo"]))))
        return Note(
            name=path.stem, kind=str(meta.get("tipo") or "conceito").lower(),
            synonyms=[str(s) for s in _as_list(meta.get("sinonimos"))], relations=relations,
            sources=[str(s) for s in _as_list(meta.get("fontes"))], status=status,
            updated=str(meta.get("atualizado") or ""), body=body, path=rel.as_posix(),
        )

    def known_acronyms(self) -> set[str]:
        """Siglas já presentes na ontologia (nomes e sinônimos em maiúsculas), tidas como definidas."""
        self.notes()
        return {t for n in self._notes for t in [n.name, *n.synonyms] if re.fullmatch(r"[A-ZÀ-Ý]{2,6}", t)}

    def _annotate(self) -> None:
        """Avisos STE-pt de cada nota (inclusive as editadas à mão)."""
        unapproved = self.unapproved_terms()
        known = self.known_acronyms()
        for note in self._notes:
            note.warnings = style.check(note.body, unapproved, known)

    # -- consulta --
    def unapproved_terms(self) -> dict[str, str]:
        """Sinônimo (sem acento, minúsculo) -> termo aprovado. Ignora sinônimos que são nome de outra nota."""
        names = {style.fold(n.name) for n in self._notes}
        out: dict[str, str] = {}
        for note in self._notes:
            if note.is_draft:
                continue
            for synonym in note.synonyms:
                key = style.fold(synonym)
                if key and key not in names and key != style.fold(note.name):
                    out[key] = note.name
        return out

    def resolve(self, name: str) -> Note | None:
        """Nota pelo nome ou sinônimo (sem acento, sem distinguir caixa). Prefere a validada."""
        key = style.fold(link_target(name))
        found = [n for n in self.notes() if key == style.fold(n.name) or key in {style.fold(s) for s in n.synonyms}]
        found.sort(key=lambda n: n.is_draft)
        return found[0] if found else None

    def search(self, text: str, include_drafts: bool = False, limit: int = 10) -> list[Note]:
        words = style.fold(text).split()
        scored = []
        for note in self.notes():
            if note.is_draft and not include_drafts:
                continue
            name = style.fold(note.name)
            syns = [style.fold(s) for s in note.synonyms]
            body = style.fold(note.body)
            if style.fold(text) == name or style.fold(text) in syns:
                score = 100
            elif all(w in name for w in words):
                score = 60
            elif any(all(w in s for w in words) for s in syns):
                score = 50
            elif all(w in f"{name} {' '.join(syns)} {body}" for w in words):
                score = 10
            else:
                continue
            scored.append((-score, note.is_draft, note.name, note))
        scored.sort(key=lambda t: t[:3])
        return [t[3] for t in scored[:limit]]

    def count_drafts_matching(self, text: str) -> int:
        return len(self.search(text, include_drafts=True, limit=1000)) - len(self.search(text, limit=1000))

    def neighbors(self, name: str, depth: int = 1, include_drafts: bool = False) -> list[tuple[int, str, str, str]]:
        """Relações a até `depth` saltos: (nível, direção '→'/'←', relação, nome). Segue os dois sentidos."""
        start = self.resolve(name)
        if start is None:
            return []
        usable = [n for n in self.notes() if include_drafts or not n.is_draft]
        by_name = {style.fold(n.name): n for n in usable}
        seen = {style.fold(start.name)}
        frontier, out = [start], []
        for level in range(1, max(1, min(depth, 2)) + 1):
            nxt = []
            for note in frontier:
                edges = [("→", rel, target) for rel, target in note.relations]
                edges += [("←", rel, other.name) for other in usable for rel, target in other.relations
                          if style.fold(target) == style.fold(note.name)]
                for arrow, rel, target in edges:
                    key = style.fold(target)
                    out.append((level, arrow, rel, target if key in by_name else f"{target} (sem nota)"))
                    if key in by_name and key not in seen:
                        seen.add(key)
                        nxt.append(by_name[key])
            frontier = nxt
        return out

    # -- cronologia --
    def events(self) -> list[tuple[str, str]]:
        """(data ISO, linha completa) de todos os arquivos de Eventos/, do mais novo para o mais antigo."""
        folder = self.root / EVENTS_DIR
        if not folder.is_dir():
            return []
        out = []
        for path in sorted(folder.glob("*.md")):
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                m = _EVENT.match(line.strip())
                if m:
                    out.append((m.group(1), line.strip()))
        out.sort(key=lambda t: t[0], reverse=True)
        return out

    def timeline(self, subject: str, since: str = "", limit: int = 30) -> list[str]:
        note = self.resolve(subject)
        terms = {style.fold(subject)}
        if note:
            terms |= {style.fold(note.name), *(style.fold(s) for s in note.synonyms)}
        terms.discard("")
        return [line for date, line in self.events()
                if (not since or date >= since) and any(t in style.fold(line) for t in terms)][:limit]

    def event_lines_since(self, since: str = "", limit: int = 30) -> list[str]:
        return [line for date, line in self.events() if not since or date >= since][:limit]
