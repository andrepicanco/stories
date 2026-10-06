"""Sanitização de HTML por lista de permissão. Vale para o que o LLM gera, o que o editor produz e o que
vai para o Azure DevOps: só tags de formatação de texto, sem scripts, estilos, eventos ou URLs perigosas."""
import re
from html import escape
from html.parser import HTMLParser

ALLOWED = {
    "p", "br", "hr", "strong", "b", "em", "i", "u", "s", "code", "pre", "blockquote",
    "h1", "h2", "h3", "h4", "ul", "ol", "li", "a",
    "table", "thead", "tbody", "tr", "th", "td",
}
VOID = {"br", "hr"}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "noscript"}
SAFE_URL = re.compile(r"^(https?://|mailto:)", re.IGNORECASE)


class _Sanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.stack: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROP_WITH_CONTENT:
            self.skip_depth += 1
            return
        if self.skip_depth or tag not in ALLOWED:
            return
        if tag == "a":
            href = next((v for k, v in attrs if k == "href" and v), "").strip()
            if not SAFE_URL.match(href):
                return                      # sem destino seguro: some a tag, o texto permanece
            self.out.append(f'<a href="{escape(href, quote=True)}" target="_blank" rel="noopener noreferrer">')
        else:
            self.out.append(f"<{tag}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and tag in self.stack and tag in ALLOWED:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in DROP_WITH_CONTENT:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if self.skip_depth or tag not in ALLOWED or tag in VOID or tag not in self.stack:
            return
        while self.stack:                       # fecha o que ficou aberto dentro
            top = self.stack.pop()
            self.out.append(f"</{top}>")
            if top == tag:
                break

    def handle_data(self, data):
        if not self.skip_depth:
            self.out.append(escape(data, quote=False))

    def result(self) -> str:
        while self.stack:
            self.out.append(f"</{self.stack.pop()}>")
        return "".join(self.out)


def sanitize_html(html: str | None) -> str:
    if not html:
        return ""
    parser = _Sanitizer()
    parser.feed(html)
    parser.close()
    return parser.result().strip()


def ensure_html(text: str | None) -> str:
    """Texto sem nenhuma tag (ex.: o modelo respondeu em texto puro) vira parágrafos HTML."""
    if not text or not text.strip():
        return ""
    if re.search(r"<[a-zA-Z][^>]*>", text):
        return sanitize_html(text)
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return "".join(f"<p>{escape(p).replace(chr(10), '<br>')}</p>" for p in paragraphs)
