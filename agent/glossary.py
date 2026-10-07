"""Glossário de domínio (Cobrança): carga do JSON e índice de aliases.

Usado pela tool `glossario_buscar` (runtime) e pelo script de conversão (relatório de aliases ambíguos),
para que os dois enxerguem exatamente os mesmos aliases."""
import json
import re
from pathlib import Path

from .text import fold

_PAREN_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")


def normalize(text: str) -> str:
    """Chave de busca: sem acento, minúsculas e espaços colapsados."""
    return " ".join(fold(text).split())


def aliases(entry: dict) -> list[str]:
    """Nome canônico + cada sinônimo. Sinônimos anotados, como 'positivação (o oposto)', também valem sem a
    anotação final entre parênteses."""
    out = []
    for name in [entry["nome_canonico"], *entry.get("sinonimos", [])]:
        out.append(name)
        stripped = _PAREN_SUFFIX.sub("", name).strip()
        if stripped and stripped != name:
            out.append(stripped)
    return out


def load_entries(path: Path) -> list[dict]:
    """Lê o JSON gerado por scripts/glossario_build.py. Levanta ValueError se o formato estiver errado."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("o glossário deve ser uma lista de entradas")
    for i, entry in enumerate(data, 1):
        if (not isinstance(entry, dict) or not str(entry.get("nome_canonico") or "").strip()
                or not isinstance(entry.get("sinonimos", []), list)):
            raise ValueError(f"entrada {i} inválida (precisa de nome_canonico e sinonimos em lista)")
    return data


class Glossary:
    def __init__(self, entries: list[dict]):
        self.entries = entries
        self._index: dict[str, list[dict]] = {}
        for entry in entries:
            for alias in aliases(entry):
                key = normalize(alias)
                if not key:
                    continue
                bucket = self._index.setdefault(key, [])
                if not any(other is entry for other in bucket):
                    bucket.append(entry)

    def lookup(self, term: str) -> list[dict]:
        """Entradas cujo nome canônico ou sinônimo é igual ao termo (match exato após normalizar)."""
        return list(self._index.get(normalize(term), []))

    @property
    def alias_count(self) -> int:
        return len(self._index)

    def ambiguous(self) -> dict[str, list[str]]:
        """Aliases que apontam para mais de uma entidade: chave normalizada -> nomes canônicos."""
        return {key: [e["nome_canonico"] for e in bucket] for key, bucket in self._index.items() if len(bucket) > 1}
