"""Harness: o loop que orquestra modelo <-> tools, com limites e guardrails.
O modelo só *pede* tools; quem executa (e decide se pode) é este código.

Mudanças em relação ao ai-agents-test: aprovação por callback (sem input()), limites configuráveis,
resultado estruturado com os passos executados e fechamento gracioso ao estourar o limite de passos."""
import json
from dataclasses import dataclass, field
from typing import Callable, Optional

LIMIT_NUDGE = ("Limite de consultas atingido. Não chame mais tools: finalize agora, usando apenas "
               "o contexto já reunido, e deixe explícito o que não conseguiu confirmar.")


@dataclass
class Step:
    tool: str
    args: str            # JSON bruto como o modelo enviou
    output: str          # o que voltou ao modelo (já truncado)
    error: bool = False


@dataclass
class TurnResult:
    text: str
    steps: list[Step] = field(default_factory=list)
    hit_step_limit: bool = False
    messages: list = field(default_factory=list)


def run_turn(
    llm,
    system_prompt: str,
    messages: list,
    tools: list,
    *,
    max_steps: int = 12,
    max_tool_output: int = 8000,
    approve: Optional[Callable[[str, dict], bool]] = None,
    on_step: Optional[Callable[[Step], None]] = None,
) -> TurnResult:
    """Roda o loop até o modelo responder sem pedir tools.

    `messages` são as mensagens user/assistant do turno (sem o system). `approve(nome, args)` decide
    tools com efeito WRITE_WORLD; sem callback, elas são negadas."""
    registry = {t.name: t for t in tools}
    specs = [t.spec() for t in tools]
    convo = [{"role": "system", "content": system_prompt}, *messages]
    result = TurnResult(text="", messages=convo)

    for _ in range(max_steps):
        msg = llm.chat(convo, specs)
        convo.append(msg.model_dump(exclude_none=True))
        if not msg.tool_calls:
            result.text = msg.content or ""
            return result
        for call in msg.tool_calls:
            raw = call.function.arguments
            output, is_error = _execute(registry, call.function.name, raw, approve, max_tool_output)
            step = Step(call.function.name, raw, output, is_error)
            result.steps.append(step)
            if on_step:
                on_step(step)
            convo.append({"role": "tool", "tool_call_id": call.id, "content": output})

    # Limite de passos: uma última chamada SEM tools força uma resposta com o que já foi coletado.
    result.hit_step_limit = True
    convo.append({"role": "user", "content": LIMIT_NUDGE})
    result.text = llm.chat(convo, []).content or ""
    return result


def _execute(registry, name, raw_args, approve, max_output) -> tuple[str, bool]:
    tool = registry.get(name)
    if tool is None:
        return f"erro: tool '{name}' não existe", True
    try:
        args = tool.check_args(json.loads(raw_args or "{}"))   # tipos validados antes de executar
        if tool.needs_approval and not (approve and approve(name, args)):
            return "negado: esta ação exige aprovação do usuário", True
        out = str(tool.fn(**args))
        error = False
    except Exception as e:                                      # erro vira observação: o modelo se corrige
        out, error = f"erro: {e}", True
    if len(out) > max_output:
        out = out[:max_output] + f"\n[... truncado: {len(out) - max_output} caracteres omitidos]"
    return out, error
