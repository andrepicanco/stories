"""Ontologia das tools: TIPOS (com herança) e EFEITOS. É o vocabulário que o harness usa para validar.
Em vez de "tudo é string", cada argumento declara o que é: Inteiro, WorkItemId, Path, Query...
(Edição da ontologia pelo usuário fica para uma versão futura.)"""
import re
from enum import Enum


class OntologyError(ValueError):
    """Violação da ontologia (tipo ou restrição). Vira observação para o modelo se corrigir."""


class Effect(str, Enum):
    READ = "READ"                  # só lê
    WRITE_MEMORY = "WRITE_MEMORY"  # grava memória do agente
    WRITE_WORLD = "WRITE_WORLD"    # muda o mundo / irreversível: exige aprovação humana


NEEDS_APPROVAL = {Effect.WRITE_WORLD}   # a política de aprovação sai do EFEITO, não de um flag por tool


def _text(v):
    if v is None or isinstance(v, (dict, list)):
        raise OntologyError("esperava texto")
    return str(v).strip()


def _query(v):
    s = re.sub(r"\s+", " ", _text(v))
    if not s or len(s) > 200:
        raise OntologyError("consulta vazia ou maior que 200 caracteres")
    return s


def _number(v):
    if isinstance(v, bool):
        raise OntologyError("booleano não é Number")
    if isinstance(v, (int, float)):
        return v
    s = _text(v)
    if re.fullmatch(r"-?\d+([.,]\d+)?", s):
        return float(s.replace(",", "."))
    raise OntologyError(f"'{v}' não é um Number")


def _positive(v):
    n = _number(v)
    if n <= 0:
        raise OntologyError(f"{n} deve ser maior que zero")
    return n


def _integer(v):
    n = _number(v)
    if n != int(n):
        raise OntologyError(f"{n} não é inteiro")
    return int(n)


def _workitem_id(v):
    n = _integer(v)
    if n <= 0:
        raise OntologyError("ID de work item deve ser maior que zero")
    return n


def _path(v):
    """Caminho relativo seguro (sem sair da raiz). Vazio significa a própria raiz."""
    s = _text(v).replace("\\", "/")
    if s.startswith("/") or ".." in s.split("/") or re.match(r"^[A-Za-z]:", s):
        raise OntologyError(f"'{s}' não é um Path relativo seguro")
    return s.strip("/")


def _url(v):
    s = _text(v)
    if not re.match(r"^https?://\S+$", s):
        raise OntologyError(f"'{s}' não é uma URL http(s)")
    return s


# nome: (tipo-pai, parser). O pai documenta a hierarquia (WorkItemId É UM Inteiro; Query É UM Text).
TYPES = {
    "Text": (None, _text), "Query": ("Text", _query), "Path": ("Text", _path), "Url": ("Text", _url),
    "Number": (None, _number), "PositiveNumber": ("Number", _positive),
    "Inteiro": ("Number", _integer), "WorkItemId": ("Inteiro", _workitem_id),
}


def is_a(t: str, ancestor: str) -> bool:
    while t:
        if t == ancestor:
            return True
        t = TYPES[t][0]
    return False


def validate(t: str, value):
    return TYPES[t][1](value)


def json_type(t: str) -> str:
    if is_a(t, "Inteiro"):
        return "integer"
    return "number" if is_a(t, "Number") else "string"
