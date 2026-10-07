"""Tools de leitura do vault do Obsidian. Tudo confinado à pasta raiz configurada em ⚙️.

Só arquivos .md; pastas ocultas (.obsidian, .git, .trash) são ignoradas. Sem pasta raiz
configurada, nenhuma tool é registrada."""
import re
from pathlib import Path

from agent.base import Param, Tool, ToolContext
from agent.ontology import Effect
from agent.text import fold as _fold

GROUP = "obsidian"
MAX_FILE_BYTES = 2_000_000
MAX_LIST = 200
MAX_SEARCH_RESULTS = 15
MAX_SNIPPETS_PER_FILE = 3


class Vault:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve(self, rel: str) -> Path:
        target = (self.root / rel).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("caminho fora da pasta raiz do Obsidian")
        if any(part.startswith(".") for part in target.relative_to(self.root).parts):
            raise ValueError("pastas e arquivos ocultos não são acessíveis")
        return target

    def notes(self):
        for path in sorted(self.root.rglob("*.md")):
            rel = path.relative_to(self.root)
            if any(part.startswith(".") for part in rel.parts) or not path.is_file():
                continue
            yield path, rel.as_posix()

    def list_dir(self, rel: str) -> str:
        folder = self.resolve(rel)
        if not folder.is_dir():
            raise ValueError(f"'{rel or '/'}' não é uma pasta")
        entries = []
        for child in sorted(folder.iterdir(), key=lambda p: (p.is_file(), p.name.casefold())):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                entries.append(f"[pasta] {child.name}/")
            elif child.suffix.lower() == ".md":
                entries.append(f"[nota]  {child.name}")
        if not entries:
            return "(vazia)"
        extra = f"\n[... {len(entries) - MAX_LIST} itens omitidos]" if len(entries) > MAX_LIST else ""
        return "\n".join(entries[:MAX_LIST]) + extra

    def read(self, rel: str, start: int, limit: int) -> str:
        path = self.resolve(rel)
        if path.suffix.lower() != ".md" or not path.is_file():
            raise ValueError(f"'{rel}' não é uma nota .md existente")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("nota grande demais (acima de 2 MB)")
        text = path.read_text(encoding="utf-8", errors="replace")
        chunk = text[start:start + limit]
        remaining = len(text) - (start + len(chunk))
        if remaining > 0:
            chunk += f"\n[... faltam {remaining} caracteres; chame de novo com start={start + len(chunk)}]"
        return chunk or "(nota vazia ou start além do fim)"

    def search(self, query: str) -> str:
        terms = [t for t in re.split(r"\s+", _fold(query)) if t]
        hits = []
        for path, rel in self.notes():
            if path.stat().st_size > MAX_FILE_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            folded = _fold(rel + "\n" + text)
            if not all(t in folded for t in terms):
                continue
            lines = text.splitlines()
            snippets = [
                f"  L{i + 1}: {line.strip()[:160]}"
                for i, line in enumerate(lines)
                if any(t in _fold(line) for t in terms)
            ][:MAX_SNIPPETS_PER_FILE]
            in_name = sum(t in _fold(rel) for t in terms)
            hits.append((-in_name, rel, snippets))   # nome do arquivo casando vem primeiro
        if not hits:
            return "nenhuma nota encontrada para essa busca"
        hits.sort()
        out = [f"{rel}\n" + "\n".join(snips) for _, rel, snips in hits[:MAX_SEARCH_RESULTS]]
        more = f"\n[... mais {len(hits) - MAX_SEARCH_RESULTS} notas casam; refine a busca]" if len(hits) > MAX_SEARCH_RESULTS else ""
        return "\n\n".join(out) + more


def get_tools(ctx: ToolContext) -> list[Tool]:
    root = (ctx.settings.get("obsidian", {}).get("root_dir") or "").strip()
    if not root or not Path(root).is_dir():
        return []
    vault = Vault(Path(root))
    read_limit = max(500, ctx.max_tool_output - 300)
    return [
        Tool(
            name="obsidian_list",
            description="Lista pastas e notas (.md) de uma pasta do vault do Obsidian do usuário.",
            inputs={"path": Param("Path", "pasta relativa à raiz do vault; vazio = raiz", optional=True)},
            fn=lambda path="": vault.list_dir(path),
            effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="obsidian_search",
            description="Busca notas do vault cujo nome ou conteúdo contém TODOS os termos (sem distinguir acentos). "
                        "Retorna caminhos e trechos.",
            inputs={"query": Param("Query", "termos de busca")},
            fn=lambda query: vault.search(query),
            effect=Effect.READ, group=GROUP,
        ),
        Tool(
            name="obsidian_read",
            description="Lê o conteúdo de uma nota .md do vault. Notas longas vêm em partes (use start).",
            inputs={
                "path": Param("Path", "caminho da nota relativo à raiz, ex.: 'Projetos/Reneg.md'"),
                "start": Param("Inteiro", "posição inicial em caracteres (padrão 0)", optional=True),
            },
            fn=lambda path, start=0: vault.read(path, max(0, start), read_limit),
            effect=Effect.READ, group=GROUP,
        ),
    ]
