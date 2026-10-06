"""Geração e iteração do card: monta a tarefa, roda o agente e valida a resposta estruturada.

Um único ponto de entrada (`generate`) atende o botão Gerar (sem resposta do usuário) e o Responder (com
resposta). Cada chamada é independente: o estado da tela (textos, comentário anterior) é reenviado inteiro."""
import json
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from integrations.html_sanitize import ensure_html

from .harness import Step, run_turn
from .mcp_bridge import manager
from .memory import Memory
from .service import build_agent

MAX_LEARNINGS = 2
MAX_LEARNING_CHARS = 240
MAX_TITLE_CHARS = 200
HISTORY_TURNS = 6

OUTPUT_CONTRACT = """## Formato da resposta (obrigatório)
Sua resposta FINAL deve ser somente um objeto JSON válido, sem texto fora dele e sem cercas de código:
{
  "mode": "draft" ou "questions",
  "title": "título curto e objetivo do card, sem emoji",
  "card_html": "texto do card em HTML",
  "impacted_resources_html": "nomes de repositórios, serviços ou sistemas que serão alterados, em HTML (um por item de lista; NÃO são cards nem links)",
  "acceptance_criteria_html": "critérios de aceite em HTML",
  "comment": "mensagem ao usuário: fontes realmente consultadas (cards, páginas, notas), o que NÃO foi encontrado, suposições e dúvidas menores",
  "questions": ["pergunta 1", "pergunta 2"],
  "feedback": {"sentiment": "positive|negative|neutral|none", "learnings": ["preferência durável"]},
  "ontology_suggestions": [{"nome": "termo", "tipo": "conceito|sistema|repositorio|fluxo|regra", "descricao": "...", "sinonimos": [], "relacoes": [{"rel": "usa", "alvo": "Outro conceito"}], "fonte": "onde você viu isso"}]
}
Regras do formato:
- Use "mode": "questions" somente se faltar informação essencial que as fontes não resolvem: então envie até 2 \
perguntas em "questions", deixe card_html, impacted_resources_html e acceptance_criteria_html vazios e não \
inclua título. Caso contrário use "draft" e deixe "questions" vazio.
- HTML permitido: p, br, strong, em, u, h2, h3, ul, ol, li, a, code, blockquote, table. Converta qualquer markdown \
das skills para HTML (títulos de seção em h2/h3, negrito em strong, listas em ul/ol).
- Critérios de aceite vão SOMENTE em acceptance_criteria_html, e recursos/repositórios SOMENTE em \
impacted_resources_html; não os repita em card_html.
- "feedback" só se aplica quando há uma resposta do usuário; sem resposta, use sentiment "none" e learnings [].
- "learnings": no máximo 2 aprendizados GERAIS e duráveis sobre como o usuário quer os textos (estilo, nível de \
detalhe, fontes preferidas), sem detalhes desta história. Um por ideia: NUNCA repita a mesma ideia com outras \
palavras. Escreva cada um como INSTRUÇÃO curta e acionável, no imperativo (ex.: "Escreva critérios de aceite \
objetivos e testáveis"), nunca como descrição vaga ("gosta de concisão"). Um pedido pontual de ajuste NÃO é aprendizado: só registre quando o usuário expressar uma preferência \
que valha para histórias futuras. Na dúvida, deixe vazio — é o caso mais comum.
- "ontology_suggestions": no máximo 3 conceitos, sistemas, fluxos ou regras de Cobrança que você aprendeu nas fontes \
e que a ontologia NÃO tem (ou contradiz). Só inclua o que uma fonte realmente afirma; "fonte" é obrigatório (página, \
card ou nota consultada) e sem fonte a sugestão é descartada. Escreva "descricao" no padrão STE-pt: frases de até 20 \
palavras, voz ativa, um termo por conceito, sigla definida na primeira vez. Se não há nada novo, use [] (o caso mais \
comum). Não repita o que a ontologia já tem."""


class GenerationError(RuntimeError):
    pass


@dataclass
class GenerationInput:
    card_type: str = "User Story"
    epic: Optional[dict] = None                      # {"id": int, "title": str}
    related: list[dict] = field(default_factory=list)  # [{"id", "title"}]
    brief: str = ""
    enabled_groups: list[str] = field(default_factory=list)
    title: str = ""
    card_html: str = ""
    resources_html: str = ""
    criteria_html: str = ""
    chat: list[dict] = field(default_factory=list)   # [{"role": "assistant"|"user", "content": str}]
    reply: str = ""


@dataclass
class GenerationResult:
    mode: str
    title: str
    card_html: str
    resources_html: str
    criteria_html: str
    comment: str
    questions: list[str]
    sentiment: str
    learnings_saved: list[str]
    steps: list[dict]
    warnings: list[str]
    hit_step_limit: bool
    ontology_suggestions_saved: list[str] = field(default_factory=list)


def build_task(inp: GenerationInput) -> str:
    parts = [f"Tipo de card: {inp.card_type}."]
    if inp.epic:
        parts.append(f"Épico: #{inp.epic['id']} — {inp.epic.get('title', '')}")
    if inp.related:
        listing = "\n".join(f"- #{c['id']} — {c.get('title', '')}" for c in inp.related)
        parts.append("Cards relacionados (filhos do mesmo épico; leia o conteúdo deles (incluindo histórico de comentários) com as tools se ajudar):\n" + listing)
    parts.append("Descrição breve e orientações do usuário:\n" + (inp.brief.strip() or "(vazia)"))

    has_draft = any(t.strip() for t in (inp.card_html, inp.resources_html, inp.criteria_html))
    if has_draft:
        parts.append(
            "Estado atual do card na tela (o usuário pode tê-lo editado: preserve as edições dele):\n"
            f"TÍTULO: {inp.title}\n\nTEXTO DO CARD (HTML):\n{inp.card_html}\n\n"
            f"RECURSOS IMPACTADOS (HTML):\n{inp.resources_html}\n\nCRITÉRIOS DE ACEITE (HTML):\n{inp.criteria_html}"
        )
    if inp.chat:
        turns = inp.chat[-HISTORY_TURNS * 2:]
        parts.append("Conversa até aqui:\n" + "\n".join(
            f"{'Você' if t['role'] == 'assistant' else 'Usuário'}: {t['content']}" for t in turns))

    if inp.reply.strip():
        parts.append(
            "RESPOSTA DO USUÁRIO:\n" + inp.reply.strip() + "\n\n"
            "Como proceder: se a resposta pede alterações ou responde suas perguntas, aplique-as e devolva os três "
            "textos COMPLETOS e atualizados (mode draft). Se for só um elogio ou crítica sem pedido de alteração, "
            "devolva os textos atuais exatamente como estão e um comentário curto. Em qualquer caso, preencha "
            "'feedback' (sentiment e learnings)."
        )
    else:
        parts.append(
            "Tarefa: reúna o contexto antes de redigir. Consulte CADA fonte habilitada que seja relevante (ex.: busque "
            "no Notion e leia as páginas pertinentes, leia os cards do Azure DevOps, procure nas notas do Obsidian; "
            "se houver ontologia disponível, comece por ela para entender os conceitos e as relações do tema); "
            "se uma fonte não trouxe nada útil, registre isso no comentário. Aplique a skill de escrita de cards "
            "adequada ao tipo (carregue-a com load_skill) e produza o card conforme o formato de saída."
        )
    return "\n\n".join(parts)


def _extract_json(text: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("a resposta não contém um objeto JSON")
    data = json.loads(cleaned[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("o JSON da resposta não é um objeto")
    return data


def parse_output(text: str) -> dict:
    """Valida e normaliza a resposta do modelo. Levanta ValueError/JSONDecodeError se inválida."""
    data = _extract_json(text)
    mode = str(data.get("mode", "draft")).strip().lower()
    if mode not in ("draft", "questions"):
        raise ValueError(f"mode inválido: {mode!r}")
    comment = str(data.get("comment") or "").strip()
    questions = [str(q).strip() for q in (data.get("questions") or []) if str(q).strip()][:2]
    feedback = data.get("feedback") if isinstance(data.get("feedback"), dict) else {}
    sentiment = str(feedback.get("sentiment", "none")).lower()
    learnings = [" ".join(str(x).split())[:MAX_LEARNING_CHARS] for x in (feedback.get("learnings") or []) if str(x).strip()]

    suggestions = [s for s in (data.get("ontology_suggestions") or []) if isinstance(s, dict)][:3]
    out = {"mode": mode, "comment": comment, "questions": questions, "ontology_suggestions": suggestions,
           "sentiment": sentiment if sentiment in ("positive", "negative", "neutral") else "none",
           "learnings": learnings[:MAX_LEARNINGS], "title": "", "card_html": "",
           "resources_html": "", "criteria_html": ""}
    if mode == "questions":
        if not questions:
            raise ValueError("mode 'questions' sem nenhuma pergunta")
        numbered = "\n".join(f"{i}. {q}" for i, q in enumerate(questions, 1))
        out["comment"] = "Antes de redigir, preciso confirmar:\n" + numbered + (f"\n\n{comment}" if comment else "")
        return out

    out["card_html"] = ensure_html(data.get("card_html"))
    if not out["card_html"]:
        raise ValueError("mode 'draft' sem card_html")
    out["resources_html"] = ensure_html(data.get("impacted_resources_html"))
    out["criteria_html"] = ensure_html(data.get("acceptance_criteria_html"))
    title = re.sub(r"^[\s📝]+", "", str(data.get("title") or "")).strip()
    out["title"] = " ".join(title.split())[:MAX_TITLE_CHARS]
    return out


def generate(
    llm,
    settings: dict,
    inp: GenerationInput,
    memory_path=None,
    on_step: Optional[Callable[[Step], None]] = None,
    wait_for_mcp: bool = True,
) -> GenerationResult:
    if wait_for_mcp:
        manager.wait_ready(20)
    kwargs = {"memory_path": memory_path} if memory_path else {}
    agent = build_agent(settings, inp.enabled_groups, **kwargs)
    system_prompt = agent.system_prompt + "\n\n" + OUTPUT_CONTRACT

    result = run_turn(llm, system_prompt, [{"role": "user", "content": build_task(inp)}], agent.tools,
                      max_steps=agent.max_steps, max_tool_output=agent.max_tool_output, on_step=on_step)
    try:
        parsed = parse_output(result.text)
    except (ValueError, json.JSONDecodeError) as first_error:
        # Uma única tentativa de conserto, sem tools, pedindo só o JSON no formato correto.
        convo = [*result.messages, {"role": "user", "content":
                 f"Sua resposta não pôde ser lida ({first_error}). Reenvie SOMENTE o objeto JSON no formato exigido."}]
        try:
            parsed = parse_output(llm.chat(convo, []).content or "")
        except (ValueError, json.JSONDecodeError) as second_error:
            raise GenerationError(f"O modelo não devolveu uma resposta válida: {second_error}") from second_error

    memory = Memory(agent.memory.path)
    saved = [fact for fact in parsed["learnings"] if inp.reply.strip() and memory.add(fact)]
    suggested: list[str] = []
    if parsed["ontology_suggestions"]:
        try:
            from .knowledge.suggestions import save_suggestions   # import tardio: evita ciclo com a ingestão
            suggested = save_suggestions(llm, settings, parsed["ontology_suggestions"])
        except Exception:  # noqa: BLE001 - a ontologia nunca pode derrubar a geração do card
            suggested = []

    return GenerationResult(
        mode=parsed["mode"], title=parsed["title"], card_html=parsed["card_html"],
        resources_html=parsed["resources_html"], criteria_html=parsed["criteria_html"],
        comment=parsed["comment"], questions=parsed["questions"], sentiment=parsed["sentiment"],
        learnings_saved=saved,
        steps=[{"tool": s.tool, "args": s.args, "error": s.error} for s in result.steps],
        warnings=agent.warnings, hit_step_limit=result.hit_step_limit,
        ontology_suggestions_saved=suggested,
    )
