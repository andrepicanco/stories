"""Extrai organização, projeto, wiki e página raiz da URL de uma página da wiki do Azure DevOps."""
from dataclasses import dataclass
from typing import Optional
from urllib.parse import unquote, urlparse


class InvalidWikiUrl(ValueError):
    pass


@dataclass(frozen=True)
class WikiContext:
    org_url: str
    project: str
    wiki: str
    page_id: Optional[int]   # página raiz; None = a wiki inteira
    slug: str                # nome da página na URL (com '-' no lugar dos espaços)


def parse_wiki_url(url: str) -> WikiContext:
    """Espera https://dev.azure.com/{org}/{projeto}/_wiki/wikis/{wiki}[/{id}[/{página}]]."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in ("http", "https") or parsed.netloc.lower() != "dev.azure.com":
        raise InvalidWikiUrl("A URL da wiki deve começar com https://dev.azure.com/.")

    parts = [unquote(p) for p in parsed.path.split("/") if p]
    if len(parts) < 5 or parts[2] != "_wiki" or parts[3] != "wikis":
        raise InvalidWikiUrl(
            "URL de wiki inválida. Copie o link de uma página da wiki, no formato "
            "https://dev.azure.com/{org}/{projeto}/_wiki/wikis/{wiki}/{id}/{página}."
        )
    page_id = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else None
    slug = parts[6] if len(parts) > 6 else ""
    return WikiContext(f"https://dev.azure.com/{parts[0]}", parts[1], parts[4], page_id, slug)
