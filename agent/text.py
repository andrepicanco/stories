"""Utilitários de texto compartilhados pelas tools e pelos scripts."""
import unicodedata


def fold(text: str) -> str:
    """Minúsculas e sem acento, para busca tolerante."""
    return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn")
