"""Converte o HTML dos campos do Azure DevOps em texto simples, para o LLM ler sem ruído."""
import re
from html.parser import HTMLParser

_BLOCK = {"p", "div", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table"}


class _Extractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.href: str | None = None
        self.link_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "li":
            self.parts.append("\n- ")
        elif tag == "a":
            self.href = dict(attrs).get("href") or None
            self.link_text = []
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "a" and self.href:
            # Links colados pelo usuário precisam chegar ao agente: "texto (url)", sem repetir a URL.
            if self.href not in "".join(self.link_text):
                self.parts.append(f" ({self.href})")
            self.href = None
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        self.parts.append(data)
        if self.href:
            self.link_text.append(data)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    extractor = _Extractor()
    extractor.feed(html)
    text = "".join(extractor.parts).replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
