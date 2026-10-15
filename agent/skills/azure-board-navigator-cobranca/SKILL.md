---
name: azure-board-navigator-cobranca
description: "Use esta skill sempre que precisar interpretar em que etapa do desenvolvimento um card do Azure Boards está, no board Stories da Squad Violet (BSF - Cobrança): o que significa cada coluna, quem é o responsável nela, o que precisa estar pronto para entrar ou sair e se o card já está em produção. Use ao relatar andamento de cards, ao avaliar cards filhos ou relacionados de um épico e ao comparar o estágio de vários cards. Não cobre o board de Épicos."
---

# Azure Board Navigator — Squad Violet

Skill de interpretação do board **Stories** do time Renegociação e Cobrança no Azure Boards. Serve para responder "em que etapa este card está e o que isso quer dizer" sem inferir pelo nome da coluna.

A fonte estruturada é o arquivo **`colunas.json`** desta skill. Carregue-o com `load_skill` (parâmetro `file`) antes de responder; este texto só diz como usá-lo.

---

## Fluxo

```
Backlog → Refining → Tech Refining → [Ready DOR] → [Planned] → In Progress
→ Waiting Validation QA → Validating QA → UAT PO/TL
→ Package Integration → Waiting Deploy → [Waiting Store] → Validating Prod → Encerrado
```

Colunas entre colchetes existem no board, mas **não são usadas** no fluxo atual do time. Se um card aparecer nelas, descreva com o `significado` do `colunas.json` e sinalize que é incomum.

O card **volta** para trás em dois pontos previstos: reprovado no QA volta ao Dev, e recusado no UAT volta ao refinamento com motivo no card. Voltar de coluna não é erro.

## Fases (agrupamento para relatórios)

| Fase | Colunas | Em produção? |
|---|---|---|
| fila | Backlog | não |
| refinamento | Refining, Tech Refining | não |
| pronto | Ready DOR, Planned | não |
| desenvolvimento | In Progress | não |
| validacao | Waiting Validation QA, Validating QA, UAT PO/TL | não |
| entrega | Package Integration, Waiting Deploy, Waiting Store | **não** |
| producao | Validating Prod | **sim** (assistida) |
| concluido | Encerrado | sim |

## Regras de leitura

1. **Coluna não é estado.** A coluna é `System.BoardColumn`; o estado é `System.State`. Divergem em quatro nomes: `UAT PO/TL` ↔ `User Acceptance Testing`, `Encerrado` ↔ `Done`, `Backlog` ↔ `To Do`, `Ready DOR` ↔ `Ready`. Prefira a coluna; use `estado_para_coluna` só quando só houver o estado.
2. **Spike é ambíguo pelo estado.** O estado `Validating` cobre as duas colunas de QA, e `In Progress` cobre de Package Integration até Validating Prod. Sem a coluna, diga que não dá para precisar a etapa.
3. **A categoria "Resolved" do Azure não é produção.** Ela cobre Package Integration, Waiting Deploy, Waiting Store e Validating Prod. Só `Validating Prod` e `Encerrado` têm `em_producao: true`.
4. **Package Integration é "aceito, falta GMUD"**, não "quase pronto em produção". Entre ele e a produção ainda há aprovações (pelo menos 1 dia) e a janela de deploy.
5. **Quem segura o card muda com a coluna** (campo `responsavel`). Quem reporta o card é quem está no Assigned To.
6. **Aceite em UAT depende do tipo:** Technical Story é aceita pelo Tech Lead (Renê); User Story pelo PO (André), que valida a experiência no front end.
7. **Cards sem coluna** (`Discontinued`, Task, Test Case, Test Suite, Test Plan, Defect) não estão no fluxo do board. Não os conte como "em andamento" nem tente colocá-los numa coluna.

## Como responder

Para cada card, entregue: **coluna** (e estado, se divergir), **fase**, **quem segura**, **o que falta para sair da coluna** (`saida_exige`) e **se está em produção**. Quando comparar vários cards, ordene pela posição em `ordem_do_fluxo`, não por ordem alfabética.

Use o `significado` do `colunas.json` em vez de parafrasear o nome da coluna. Não deduza prazo, risco ou atraso só pela coluna: isso exige datas e histórico do card.

## O que esta skill não faz

- Não move card, não troca Assigned To e não decide status.
- Não estima prazo: a coluna diz onde o card está, não quando ele chega.
- Não cobre o board de Épicos, Planos de ação nem Fragilidades e Riscos.
- Se coluna e estado do card não bateram com `colunas.json`, **sinalize a divergência** em vez de forçar um encaixe: o board pode ter mudado desde o levantamento (2026-10-15).

## Fontes

- API do Azure DevOps: colunas, WIP e mapeamento de estados do board Stories (levantado em 2026-10-15).
- Wiki do time: *Operacional/SDLC/SDLC Renegociacao e Cobranca* (donos, gates e evidências) e *Gestao/Rito daily e rastreio* (Assigned To por etapa).
- A página *Governança Ágil/Fluxo do Board e Processos* é herdada do projeto Conta Bemol e está desatualizada (nomes antigos, sem UAT PO/TL nem Waiting Store). **Não use como fonte.**
