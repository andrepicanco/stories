---
name: story-writer-cobranca
description: "Use esta skill sempre que o usuário pedir para criar, escrever ou adaptar histórias de usuário (User Stories), histórias técnicas (Technical Stories) ou spikes no padrão do Squad Violet da Bemol Serviços Financeiros (BSF - Cobrança). Isso inclui pedidos como 'crie a história de X', 'escreva o card de Y', 'quero criar uma user story para Z', 'me ajuda a escrever o card técnico de W', 'cria o spike de investigação de X'. A skill cobre a busca de contexto no Azure Boards (com prioridade para os cards relacionados) e no Notion, as perguntas de validação com o usuário e a geração do texto final no formato correto para o Azure DevOps."
---
# Story Writer — BSF Cobrança (Squad Violet)

Skill para construir o texto de User Stories, Technical Stories e Spikes do Squad Violet da Bemol
Serviços Financeiros, no formato padrão esperado pelo time de desenvolvimento para uso no Azure DevOps.

Os cards gerados por esta skill são consumidos por IAs durante o refinamento técnico e pela esteira
de desenvolvimento — precisão e completude do escopo são essenciais.

---

## Fluxo de execução

### 1. Identificar o tipo de card

Antes de qualquer outra coisa, identifique se o card é:

- **User Story** — há um usuário final ou operador com uma necessidade concreta
- **Technical Story** — o card trata de infraestrutura, integração, refatoração ou qualquer entrega
  sem impacto perceptível direto ao usuário final
- **Spike** — o objetivo é produzir conhecimento ou uma decisão, não software funcionando;
  a entrega é um documento, recomendação ou PoC

O usuário pode indicar isso explicitamente. Se não indicar, infira pelo contexto e confirme antes
de escrever.

> A seção "História de Usuário" (Como / Quero / Para que) é **omitida** em Technical Stories e
> **sempre omitida** em Spikes.
> Spikes usam um formato próprio — ver seção "Formato do card: Spike" abaixo.

---

### 2. Buscar contexto no Azure Boards e na documentação

**Sempre** busque contexto antes de escrever, começando pelo Azure Boards. Esta etapa é obrigatória —
não pule mesmo que o usuário tenha fornecido uma descrição detalhada.

**2.1 Azure Boards (obrigatório, primeiro)**

1. **Cards relacionados marcados pelo usuário são a fonte de contexto prioritária.** Leia **cada um**
   com `azure_get_work_item` (descrição, critérios de aceite, recursos impactados, links) e, quando
   disponíveis, as tools do Azure Boards MCP para comentários, histórico e relações. Não pule nenhum
   e não resuma pelo título: regras, decisões, restrições e dependências já registradas ali devem
   orientar o novo card e ser respeitadas por ele.
2. Leia o **épico** informado (`azure_get_work_item`) e seus filhos diretos (`azure_list_epic_children`)
   para entender o recorte já existente e evitar sobreposição.
3. Busque por termos do tema (`azure_search_work_items`) para encontrar cards semelhantes, anteriores
   ou conflitantes que o usuário não tenha marcado. Se um deles afetar o escopo, trate-o como
   dependência, conflito ou item de "Fora de escopo" — não o absorva ao escopo do novo card.
4. Se um card lido referenciar outros cards que sejam decisivos para o escopo (pai, predecessor,
   dependência), leia-os também.

**2.2 Documentação de apoio**

- Notion: use a skill `notion-navigator-cobranca` (`notion-search` com o tema, épico ou funcionalidade;
  depois `notion-fetch` para ler a página completa)
- Wiki do time e Obsidian, quando habilitados
- Imagens, arquivos, links ou outros materiais que o usuário tiver anexado na conversa

**Regras**

- A única exceção à busca em documentação (2.2) é quando o usuário informar explicitamente que o
  contexto está completo na mensagem. A leitura dos cards relacionados (2.1) **nunca** é dispensada.
- Se o Azure Boards estiver indisponível nesta execução, diga isso no comentário e siga com o que o
  usuário e as demais fontes fornecerem.
- Não preencha lacunas de escopo, regra de negócio ou comportamento com suposições. O que as fontes
  não resolverem vira pergunta de validação (passo 3) ou lacuna sinalizada no comentário.
- Informe no comentário quais cards e páginas foram realmente consultados e o que **não** foi
  encontrado.

---

### 3. Fazer perguntas de validação

Faça **no máximo 2 perguntas** antes de escrever, priorizando as lacunas que impactam critérios
de aceite ou escopo. Exemplos:

- Qual é o comportamento esperado quando [condição de erro ou edge case]?
- Esse card depende de outro card ou de um time externo?
- O fluxo envolve mais de uma tela ou mais de uma chamada de API?
- Existe restrição de escopo relevante para o desenvolvimento?
- O que precisa poder ser respondido ou monitorado depois da entrega (observabilidade)?

Aguarde as respostas antes de escrever.

---

### 4. Gerar o texto do card

Use **exatamente** um dos formatos abaixo, conforme o tipo identificado.

Objetivo desta estrutura: manter o card enxuto para o Discovery, mas já pronto para o refinamento
(ver "Prontidão para o refinamento"): sem lacunas de escopo, observabilidade, dependência e aceites.

> **Onde cada parte vai na resposta da aplicação:** a seção "Recursos impactados" vai somente no
> campo de recursos impactados, e a seção "Critérios de Aceite" somente no campo de critérios de
> aceite — ambas **não** se repetem no texto do card. As demais seções compõem o texto do card.

---

## Formato do card: User Story

```
## Contexto & Escopo

### Problema a ser resolvido
[Descrição objetiva do AS IS e do gap que motiva o card.]

### Objetivo a ser alcançado
[Resultado esperado no TO BE + valor de negócio/operação desbloqueado agora.]

### Escopo do incremento
[Escopo funcional desta entrega. Indicar se envolve front, back, SAP, mensageria,
fila, registro etc., sem detalhar implementação.]

---

## História de Usuário

> Como **[persona específica]**, quero **[ação/necessidade]**, para que **[valor]**.

---

## Mudanças esperadas (quando aplicável)

### Frontend
- Fluxo/telas impactadas: [listar quando houver mudança de UI ou fluxo]
- Link de referência (Figma ou equivalente): [opcional]

### Backend
- APIs/jobs/processos/banco impactados: [visão funcional, sem payload completo]
- Link de documentação técnica existente: [opcional]

---

## Impactos, Integrações & Dependências

- **Sistemas e APIs afetados:** [internos, externos, parceiros]
- **Times/parceiros envolvidos:** [time e ponto focal, quando houver]
- **Dependências:** [cards/times/sistemas com dono e chamado/SLA, quando houver]
- **Sem dependência bloqueante:** [usar esta frase quando o incremento segue sozinho]

---

## Restrições e premissas

- **Retrocompatibilidade:** [o que precisa ser preservado; breaking change somente se explícito]
- **Regras de dado/canal/contrato:** [limite, formato, nulo, canal ou tipo de contrato quando couber]

---

## Observabilidade

- **Pergunta/resultado a monitorar:** [qual resultado de negócio/operação deve ser respondido]
- **Ou, quando não exigir instrumentação nova:** ["Não requer nova observabilidade neste
  incremento porque ..."]
- **Meios de registro esperados:** [evento, log, trace, dashboard ou fonte existente, sem prescrever
  implementação]

---

## Fora de escopo

- [Item explicitamente fora deste incremento]
- [Se não houver exclusões relevantes, escrever: "Sem itens adicionais fora de escopo."]

---

## Critérios de Aceite

**CA1** — [Critério verificável por resultado]
**CA2** — [Cenário positivo ou negativo relevante]
**CA3** — [Edge case ou restrição relevante]

---

## Recursos impactados

- [Lista de serviços, repositórios e sistemas afetados por este incremento]
```

---

## Formato do card: Technical Story

Technical Story segue o mesmo formato da User Story, com uma diferença: **não incluir** a seção
`História de Usuário`. Nas demais seções, o foco é o gap técnico/operacional e o valor técnico ou
operacional desta priorização, em vez do valor para um usuário final.

---

## Formato do card: Spike

Spikes têm estrutura própria. A entrega não é software — é conhecimento ou uma decisão.
Use este formato quando o tipo identificado for Spike.

```
## Contexto e Problema

**Situação atual:** [O que não sabemos ou o que está bloqueando uma decisão — sem solução
implícita.]

**Perguntas a responder:**
- [Pergunta objetiva 1]
- [Pergunta objetiva 2]

---

## Objetivo

[Por que precisamos dessa resposta agora — qual card, decisão ou entrega está bloqueada sem
esse conhecimento.]

---

## Impactos, Integrações & Dependências

- **Sistemas e APIs afetados:** [quando houver]
- **Dependências:** [cards/times/sistemas com dono e chamado/SLA, quando houver]
- **Sem dependência bloqueante:** [usar esta frase quando o spike segue sozinho]

---

## Abordagem sugerida

[O que o time deve investigar, testar ou consultar para responder às perguntas — fontes,
funções, sistemas, pessoas a acionar.]

---

## Fora de escopo

- [O que não precisa ser respondido neste spike]
- [Se não houver exclusões relevantes, escrever: "Sem itens adicionais fora de escopo."]

---

## Documentação de referência

-

---

## Definição de pronto

**DP1** — [Entregável concreto: decisão registrada, documento na wiki, PoC, recomendação
com trade-offs]
**DP2** — [...]

---

## Recursos impactados

- [Serviços, repositórios e sistemas que este spike pode tocar ou consultar]
```

---

## Diretrizes de qualidade: User Story, Technical Story e Spike

### Perguntas a responder (Spike)

- Devem ser objetivas e verificáveis — a resposta deve ser possível de registrar em documento
- Evitar perguntas abertas demais ("como funciona X?") — preferir ("quais regras X aplica
  para calcular Y em contratos do tipo Z?")

### Abordagem sugerida (Spike)

- Indicar fontes concretas: funções SAP, páginas do Notion, pessoas a consultar, sistemas a testar
- Não prescrever a solução — apenas orientar a investigação

### Definição de pronto (Spike)

- Diferente de Critérios de Aceite: não verifica comportamento do sistema, verifica se o
  conhecimento foi produzido e registrado
- Deve incluir quem valida o entregável antes de considerar o spike concluído (ex: área de
  negócio, Tech Lead, executivo responsável pela decisão)

### Contexto e Problema

- AS IS deve descrever o estado atual com precisão — sem julgamento, sem solução implícita
- TO BE deve descrever o resultado esperado, não a tarefa técnica a executar

### Objetivo e escopo

- O objetivo responde "por quê agora" — não é uma repetição do TO BE
- Evitar objetivos vagos como "melhorar a experiência" sem ancoragem em contexto real
- O escopo deve dizer claramente o que entra neste incremento (sem receita de implementação)

### História de Usuário

- A persona deve ser específica — não "usuário", mas "operador de loja", "atendente SAC",
  "cliente Diamante Plus com dívida em aberto"
- A ação deve estar na voz do usuário, não do negócio
- O valor deve refletir o benefício para o usuário — não o objetivo da Bemol disfarçado

### Mudanças esperadas

- Registrar o impacto esperado em frontend e backend quando aplicável
- Não transformar em plano técnico detalhado — sem payload completo, classe, query ou passo de
  implementação

### Impactos, integrações e dependências

- Listar dependências de outros cards pelo ID quando conhecido (ex: [#260535])
- Toda dependência deve ter dono (time/pessoa) e, quando houver, chamado/SLA
- Se não houver bloqueio externo, declarar explicitamente que o incremento segue sozinho
- Listar sistemas e APIs afetados no nível que o desenvolvedor precisa para estimar

### Restrições e premissas

- Declarar a retrocompatibilidade esperada; breaking change só quando explícito
- Registrar regras de dado/canal/contrato quando forem relevantes para o aceite e o escopo

### Observabilidade

- Obrigatória em toda User Story e Technical Story
- Deve trazer a pergunta/resultado a monitorar **ou** a justificativa explícita de que não requer
  nova observabilidade neste incremento
- Não inventar a pergunta de observabilidade: se o contexto não a trouxer, perguntar ao usuário
- Não pedir nome de métrica, biblioteca, dashboard ou query — isso não é requisito de Discovery

### Fora de escopo

- A seção é obrigatória
- Quando não houver exclusão relevante, usar: "Sem itens adicionais fora de escopo."
- Exemplos de exclusão: card que trata só de Pix mas o contexto sugere Boleto também; card que
  trata de exibição mas o contexto sugere que o dev pode tentar implementar a lógica de negócio junto

### Critérios de Aceite

- Cada CA deve ser verificável de forma objetiva — comportamento do sistema ou do usuário,
  não tarefa interna do time
- Numeração simples: CA1, CA2, CA3... sem agrupamentos temáticos
- Cobrir: happy path, estados de erro relevantes, edge cases identificados no contexto e, quando a
  regra tiver exclusão, o que **não** deve acontecer
- Não incluir CAs que dependam de decisões ainda em aberto — nesses casos, registrar como
  ponto em aberto no comentário (fora do formato oficial)

### Recursos impactados

- Listar serviços, repositórios e sistemas afetados por este incremento
- Evitar lista genérica; indicar apenas o que realmente entra no escopo

---

## Prontidão para o refinamento

Depois de criado, o card passa pelo refinamento (skill `refinar-card`, fora do escopo desta skill),
que avalia se ele está pronto para seguir na esteira. Esta skill **não** executa essa avaliação nem
emite veredito — apenas escreve o card de modo que ele já nasça sem as lacunas que o refinamento
devolveria. Para isso:

- **Não complete regra de negócio por inferência.** Regra, cálculo, SLA, API ou comportamento que
  nenhuma fonte trouxe vira pergunta ao usuário ou ponto em aberto no comentário.
- **Todas as seções obrigatórias preenchidas:** contexto e problema, objetivo, escopo e fora de
  escopo, restrições, critérios de aceite, observabilidade, dependências (com dono) ou a frase de que
  segue sozinho, e recursos impactados.
- **Retrocompatível por padrão.** Breaking change só se estiver explícito.
- **Incremento entregável sozinho.** O card deve ter um resultado observável de valor, um caminho de
  verificação e poder ir a produção sem depender de outro card da mesma mudança. Se o pedido reunir
  dois ou mais incrementos que poderiam subir independentemente, **não** os junte em um único card:
  sinalize no comentário e pergunte ao usuário como recortar.
- **Task não é entregável.** Dependências e recortes são tratados como outros cards (história ou
  bug), nunca como Tasks.
- **Não puxe feature vizinha para o escopo.** Interação com outro card vira dependência, conflito
  ou "Fora de escopo", não expansão automática.
- **Sem desenho técnico.** Nada de plano de testes, massa de dados, classes, payloads completos,
  métricas, dashboards ou queries.
- **Termo de negócio** que o time não usa no dia a dia recebe uma linha de glossário no próprio card.

---

## Referências de contexto

- Fonte primária de contexto: **Azure Boards** (cards relacionados, épico e cards semelhantes)
- Workspace Notion: **BSF - Cobrança**
- Database de épicos: **Tarefas** (títulos com 👑)
- Épicos de referência do Portal Web:
  - 👑 Portal Renegociação (interno) — ID `353adafb-d762-80a2-82f4-e5a086a7bd45`
  - 👑 CRM de Cobrança — ID `34aadafbd762803aa285f1881a5358b6`
- API de Renegociação BSF: documentada no Manual de Integração ASSESSORIAS v3 (PRD)
  — disponível como arquivo de projeto
- Arquitetura: SAP → Middleware C# → CobranSaaS / API BSF
- Formato de destino: Azure DevOps do Board Renegociação e Cobrança
