"""Memória de longo prazo: fatos em um JSON, persistidos entre sessões.
Alimentada pelo feedback do usuário (fase 5) e injetada no system prompt a cada execução."""
import json
from pathlib import Path

MAX_FACTS_IN_PROMPT = 50


class Memory:
    def __init__(self, path: Path):
        self.path = Path(path)

    def facts(self) -> list[str]:
        if not self.path.exists():
            return []
        return json.loads(self.path.read_text(encoding="utf-8"))

    def add(self, fact: str) -> bool:
        """Adiciona um fato (sem duplicar, ignorando caixa e espaços). Retorna se gravou."""
        fact = " ".join(fact.split())
        if not fact:
            return False
        facts = self.facts()
        if fact.casefold() in {f.casefold() for f in facts}:
            return False
        facts.append(fact)
        self._write(facts)
        return True

    def remove(self, index: int) -> None:
        facts = self.facts()
        del facts[index]
        self._write(facts)

    def _write(self, facts: list[str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")

    def prompt_block(self) -> str:
        """Texto injetado no system prompt; vazio se não há fatos."""
        facts = self.facts()[-MAX_FACTS_IN_PROMPT:]
        if not facts:
            return ""
        return "## Memória (aprendizados de histórias anteriores)\n" + "\n".join(f"- {f}" for f in facts)
