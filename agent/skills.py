"""Skills: pastas `<skills_dir>/<nome>/SKILL.md` com cabeçalho `name` e `description`.

Divulgação progressiva: o system prompt leva só o índice (nome + descrição). O texto completo
só entra no contexto quando o agente chama a tool `load_skill`."""
from dataclasses import dataclass
from pathlib import Path

from .base import CORE, Param, Tool
from .ontology import Effect

SKILL_FILE = "SKILL.md"


@dataclass
class Skill:
    name: str
    description: str
    dir: Path

    @property
    def path(self) -> Path:
        return self.dir / SKILL_FILE


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Lê um cabeçalho `---` com linhas `chave: valor` (valores podem estar entre aspas)."""
    text = text.lstrip("﻿")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text
    meta: dict[str, str] = {}
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return meta, "\n".join(lines[i + 1:]).lstrip("\n")
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip().strip('"').strip("'")
    return {}, text  # cabeçalho sem fechamento: trata tudo como corpo


class SkillRegistry:
    def __init__(self, skills_dir: Path):
        self.dir = Path(skills_dir)
        self.skills: dict[str, Skill] = {}
        self.errors: list[str] = []
        self.reload()

    def reload(self) -> None:
        self.skills, self.errors = {}, []
        if not self.dir.is_dir():
            return
        for folder in sorted(p for p in self.dir.iterdir() if p.is_dir()):
            skill_file = folder / SKILL_FILE
            if not skill_file.is_file():
                continue
            meta, _ = parse_frontmatter(skill_file.read_text(encoding="utf-8"))
            name = meta.get("name") or folder.name
            if not meta.get("description"):
                self.errors.append(f"{folder.name}: SKILL.md sem 'description' no cabeçalho")
                continue
            if name in self.skills:
                self.errors.append(f"{folder.name}: nome de skill duplicado '{name}'")
                continue
            self.skills[name] = Skill(name, meta["description"], folder)

    def index_block(self) -> str:
        if not self.skills:
            return ""
        lines = [f"- **{s.name}**: {s.description}" for s in self.skills.values()]
        return ("## Skills disponíveis\n"
                "Chame `load_skill(name)` para ler as instruções completas ANTES de aplicar uma skill.\n"
                + "\n".join(lines))

    def load(self, name: str, file: str | None = None) -> str:
        skill = self.skills.get(name)
        if skill is None:
            raise ValueError(f"skill '{name}' não existe. Disponíveis: {', '.join(self.skills) or 'nenhuma'}")
        if file is None:
            _, body = parse_frontmatter(skill.path.read_text(encoding="utf-8"))
            return body
        target = (skill.dir / file).resolve()
        if not target.is_relative_to(skill.dir.resolve()) or not target.is_file():
            raise ValueError(f"arquivo '{file}' não encontrado dentro da skill '{name}'")
        return target.read_text(encoding="utf-8")

    def tool(self) -> Tool:
        names = list(self.skills)
        return Tool(
            name="load_skill",
            description="Carrega as instruções completas de uma skill (ou um arquivo auxiliar dela).",
            inputs={
                "name": Param("Text", "nome da skill", enum=names or None),
                "file": Param("Path", "arquivo auxiliar dentro da skill (opcional)", optional=True),
            },
            fn=lambda name, file=None: self.load(name, file),
            effect=Effect.READ,
            group=CORE,
        )
