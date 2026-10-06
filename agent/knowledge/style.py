"""Verificador do padrão STE-pt (ASD-STE100 em português, rigor "80%").

Heurístico e sem dependências: devolve AVISOS, nunca bloqueia. Regras medidas: tamanho da frase, tamanho do
parágrafo, voz passiva, termos não aprovados (sinônimos de outras notas), "etc.", parênteses longos e
siglas sem definição. O texto das regras para o modelo fica em ste_pt.md."""
import re
import unicodedata

MAX_WORDS = 25            # a meta é 20; acima de 25 é violação
MAX_SENTENCES = 6
MAX_PAREN_WORDS = 8

_WORD = re.compile(r"\w+", re.UNICODE)
_PASSIVE = re.compile(
    r"\b(?:é|são|foi|foram|será|serão|está|estão|fica|ficam|ficou|ficaram)\s+\w+(?:ad[oa]s?|id[oa]s?|"
    r"t[oa]s?|s[oa]s?)\s+(?:por|pel[oa]s?)\b", re.IGNORECASE)
_ACRONYM = re.compile(r"\b[A-ZÀ-Ý]{2,6}\b")
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def fold(text: str) -> str:
    """Minúsculas e sem acento."""
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn")


def _clean(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", lambda m: m.group(2) or m.group(1), text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"[*_`>#]", "", text)


def _words(text: str) -> int:
    return len(_WORD.findall(text))


def _short(text: str, size: int = 70) -> str:
    text = " ".join(text.split())
    return text if len(text) <= size else text[:size - 1] + "…"


def check(text: str, unapproved: dict[str, str] | None = None, known_acronyms: set[str] | None = None) -> list[str]:
    """Avisos do texto. `unapproved` mapeia termo não aprovado (sem acento, minúsculo) -> termo aprovado.
    `known_acronyms` são siglas já definidas na ontologia (nomes e sinônimos), em maiúsculas."""
    warnings: list[str] = []
    cleaned = _clean(text)
    unapproved = unapproved or {}
    known = {a.upper() for a in (known_acronyms or set())}

    for paragraph in [p for p in re.split(r"\n\s*\n", cleaned) if p.strip()]:
        sentences: list[str] = []
        for line in paragraph.splitlines():
            line = re.sub(r"^\s*(?:[-+]|\d+[.)])\s+", "", line).strip()
            if line:
                sentences.extend(s for s in _SENTENCE_END.split(line) if s.strip())
        for sentence in sentences:
            n = _words(sentence)
            if n > MAX_WORDS:
                warnings.append(f"frase longa ({n} palavras, máximo {MAX_WORDS}): «{_short(sentence)}»")
        if len(sentences) > MAX_SENTENCES:
            warnings.append(f"parágrafo longo ({len(sentences)} frases, máximo {MAX_SENTENCES}): «{_short(paragraph)}»")

    for m in _PASSIVE.finditer(cleaned):
        warnings.append(f"voz passiva: «{_short(m.group(0))}»")
    if re.search(r"\betc\b\.?", cleaned, re.IGNORECASE):
        warnings.append("não use «etc.»: liste os itens")
    for m in re.finditer(r"\(([^)]*)\)", cleaned):
        if _words(m.group(1)) > MAX_PAREN_WORDS:
            warnings.append(f"parênteses longos: «{_short(m.group(0))}»")

    folded = fold(cleaned)
    for term, approved in unapproved.items():
        if len(term) >= 3 and re.search(rf"(?<!\w){re.escape(term)}(?!\w)", folded):
            warnings.append(f"termo não aprovado «{term}»: use «{approved}»")

    defined = {m.group(1).upper() for m in re.finditer(r"\(([A-ZÀ-Ý]{2,6})\)", cleaned)}
    seen: set[str] = set()
    for m in _ACRONYM.finditer(cleaned):
        acronym = m.group(0).upper()
        if acronym not in known and acronym not in defined and acronym not in seen:
            seen.add(acronym)
            warnings.append(f"sigla sem definição: {acronym}")
    return warnings
