"""Detecção de segredos em texto, para NÃO enviar ao modelo nem copiar para as notas da ontologia.

Devolve só os TIPOS encontrados, nunca o trecho. Páginas com segredo são puladas e listadas no relatório."""
import re

_PATTERNS = {
    "chave privada": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "token Bearer": re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}", re.IGNORECASE),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    "credencial em URL": re.compile(r"[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@", re.IGNORECASE),
    "senha/segredo atribuído": re.compile(
        r"(?i)\b(?:senha|password|passwd|pwd|secret|segredo|api[_-]?key|access[_-]?key|client[_-]?secret|token|pat)\b"
        r"\s*[:=]\s*[\"']?(?!\s)[^\s\"']{8,}"),
    "PAT do Azure DevOps": re.compile(r"\b[a-z0-9]{52}\b"),
    "chave da AWS": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def find_secrets(text: str) -> list[str]:
    return [kind for kind, pattern in _PATTERNS.items() if pattern.search(text or "")]
