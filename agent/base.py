"""Contrato de uma tool: função Python + argumentos tipados (ontologia) ou JSON Schema bruto + efeito.

Mudanças em relação ao ai-agents-test:
- `schema`: JSON Schema bruto, necessário para tools vindas de servidores MCP.
- `group`: a qual fonte de contexto a tool pertence (notion, azure, obsidian, core). É o que os
  checkboxes da tela liberam ou bloqueiam por execução."""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from .ontology import NEEDS_APPROVAL, Effect, OntologyError, json_type, validate

CORE = "core"   # sempre disponível (ex.: load_skill)


@dataclass
class Param:
    type: str                      # nome do tipo na ontologia: Inteiro, WorkItemId, Path, Query...
    desc: str
    optional: bool = False
    enum: Optional[list] = None


@dataclass
class Tool:
    name: str
    description: str
    fn: Callable[..., str]
    inputs: Optional[dict[str, Param]] = None
    schema: Optional[dict] = None          # JSON Schema bruto (alternativa a `inputs`)
    effect: Effect = Effect.READ
    group: str = CORE

    def __post_init__(self):
        if (self.inputs is None) == (self.schema is None):
            raise ValueError(f"tool '{self.name}': informe `inputs` OU `schema`")

    @property
    def needs_approval(self) -> bool:   # política derivada do efeito
        return self.effect in NEEDS_APPROVAL

    def spec(self) -> dict:   # formato esperado pela API
        if self.schema is not None:
            parameters = self.schema
        else:
            props = {}
            for k, p in self.inputs.items():
                props[k] = {"type": json_type(p.type), "description": f"[{p.type}] {p.desc}"}
                if p.enum:
                    props[k]["enum"] = p.enum
            parameters = {"type": "object", "properties": props,
                          "required": [k for k, p in self.inputs.items() if not p.optional]}
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                                                 "parameters": parameters}}

    def check_args(self, args: dict) -> dict:
        """Valida e normaliza os argumentos ANTES de executar."""
        if not isinstance(args, dict):
            raise OntologyError("os argumentos devem ser um objeto JSON")
        if self.schema is not None:
            missing = [k for k in self.schema.get("required", []) if args.get(k) in (None, "")]
            if missing:
                raise OntologyError(f"falta(m) o(s) argumento(s): {', '.join(missing)}")
            return args
        unknown = set(args) - set(self.inputs)
        if unknown:
            raise OntologyError(f"argumento(s) desconhecido(s): {', '.join(sorted(unknown))}")
        out = {}
        for k, p in self.inputs.items():
            v = args.get(k)
            if v is None or v == "":
                if p.optional:
                    continue
                raise OntologyError(f"falta o argumento '{k}' ({p.type})")
            try:
                out[k] = validate(p.type, v)
            except OntologyError as e:
                raise OntologyError(f"argumento '{k}' espera {p.type}: {e}")
            if p.enum and out[k] not in p.enum:
                raise OntologyError(f"argumento '{k}' deve ser um de {p.enum}")
        return out


@dataclass
class ToolContext:
    """O que os módulos de tools recebem para se configurarem."""
    settings: dict
    root: Path
    max_tool_output: int = 8000
    extra: dict = field(default_factory=dict)
