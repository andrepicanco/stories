---
name: user-story-writer-cobranca
description: "Use esta skill sempre que o usuário pedir para criar, escrever ou adaptar histórias de usuário (User Stories), histórias técnicas (Technical Stories) ou spikes no padrão do Squad Violet da Bemol Serviços Financeiros (BSF - Cobrança). Isso inclui pedidos como 'crie a história de X', 'escreva o card de Y', 'quero criar uma user story para Z', 'me ajuda a escrever o card técnico de W', 'cria o spike de investigação de X'. A skill cobre a busca de contexto no Notion, as perguntas de validação com o usuário e a geração do texto final no formato correto para o Azure DevOps."
---
 
# User Story Writer — BSF Cobrança (Squad Violet)
 
Skill para construir o texto de User Stories e Technical Stories do Squad Violet da Bemol Serviços
Financeiros, no formato padrão esperado pelo time de desenvolvimento para uso no Azure DevOps.
 
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
 
### 2. Buscar contexto no Notion
 
**Sempre** busque contexto no Notion antes de escrever, usando a skill `notion-navigator-cobran`.
Esta etapa é obrigatória — não pule mesmo que o usuário tenha fornecido uma descrição detalhada.
 
- Use `notion-search` com o tema, épico ou funcionalidade mencionados
- Após encontrar, use `notion-fetch` para ler o conteúdo completo da página
- Complemente com imagens, arquivos, links ou outros materiais que o usuário tiver anexado na conversa
A única exceção é quando o usuário informar explicitamente que o contexto está completo na
mensagem e não há página relacionada no Notion.
 
Se o Notion não retornar contexto útil, siga com o que o usuário forneceu e sinalize as lacunas.
 
---
 
### 3. Fazer perguntas de validação
 
Faça **no máximo 2 perguntas** antes de escrever, priorizando as lacunas que impactam critérios
de aceite ou escopo. Exemplos:
 
- Qual é o comportamento esperado quando [condição de erro ou edge case]?
- Esse card depende de outro card ou de um time externo?
- O fluxo envolve mais de uma tela ou mais de uma chamada de API?
- Existe restrição de escopo relevante para o MVP?
Aguarde as respostas antes de escrever.
 
---
 
### 4. Gerar o texto do card
 
Use **exatamente** o formato abaixo, respeitando as regras de omissão de seções.
 
---
 
## Formato do card
 
```
## Contexto e Problema
 
**Situação atual:** [Descrição objetiva do AS IS — como o processo ou sistema funciona hoje,
destacando a limitação ou gap que motiva o card.]
 
**Situação desejada:** [Descrição objetiva do TO BE — o que deve mudar ou passar a existir
após a entrega deste card.]
 
---
 
## Objetivo
 
[Uma ou duas frases explicando por que estamos propondo esta tarefa agora — o que desbloqueamos,
qual risco mitigamos ou qual valor entregamos ao priorizar isso neste momento.]
 
---
 
## História de Usuário
 
> Como **[persona]**, quero **[ação ou necessidade]**, para que **[valor ou objetivo]**.
 
*(Omitir esta seção em Technical Stories)*
 
---
 
## Fluxo resumido
 
*(Incluir apenas quando a história envolver mais de uma tela ou mais de uma chamada de API)*
 
1. [Passo 1]
2. [Passo 2]
3. [...]
 
---
 
## Análise de impacto
 
- **Dependências:** [Cards, times ou sistemas externos que este card depende ou que dependem dele]
- **Objetos afetados:** [Tabelas, endpoints, serviços, componentes de front que podem ser impactados]
 
*(Omitir esta seção se não houver dependências ou impactos relevantes identificados)*
 
---
 
## Fora de escopo
 
- [Item explicitamente excluído 1]
- [Item explicitamente excluído 2]
 
*(Incluir apenas quando houver risco real de o desenvolvedor ou IA interpretar o escopo de forma
mais ampla do que o pretendido)*
 
---
 
## Documentação na wiki
 
- [Deixar em branco — o PM irá linkar as referências no Azure]
 
---
 
## Critérios de Aceite
 
**CA1** — [Critério verificável e orientado ao comportamento esperado do sistema ou do usuário]
**CA2** — [...]
**CA3** — [...]
```
 
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
 
## Abordagem sugerida
 
[O que o time deve investigar, testar ou consultar para responder às perguntas — fontes,
funções, sistemas, pessoas a acionar.]
 
---
 
## Fora de escopo
 
- [O que não precisa ser respondido neste spike]
 
*(Incluir apenas quando houver risco de o time expandir a investigação além do necessário)*
 
---
 
## Documentação na wiki
 
-
 
---
 
## Definição de pronto
 
**DP1** — [Entregável concreto: decisão registrada, documento na wiki, PoC, recomendação
com trade-offs]
**DP2** — [...]
```
 
---
 
## Diretrizes de qualidade: User Story e Technical Story: Spike
 
### Perguntas a responder
- Devem ser objetivas e verificáveis — a resposta deve ser possível de registrar em documento
- Evitar perguntas abertas demais ("como funciona X?") — preferir ("quais regras X aplica
  para calcular Y em contratos do tipo Z?")
### Abordagem sugerida
- Indicar fontes concretas: funções SAP, páginas do Notion, pessoas a consultar, sistemas a testar
- Não prescrever a solução — apenas orientar a investigação
### Definição de pronto
- Diferente de Critérios de Aceite: não verifica comportamento do sistema, verifica se o
  conhecimento foi produzido e registrado
- Deve incluir quem valida o entregável antes de considerar o spike concluído (ex: área de
  negócio, Tech Lead, executivo responsável pela decisão)
### Contexto e Problema
- AS IS deve descrever o estado atual com precisão — sem julgamento, sem solução implícita
- TO BE deve descrever o resultado esperado, não a tarefa técnica a executar
### Objetivo
- Responde "por quê agora" — não é uma repetição do TO BE
- Evitar objetivos vagos como "melhorar a experiência" sem ancoragem em contexto real
### História de Usuário
- A persona deve ser específica — não "usuário", mas "operador de loja", "atendente SAC",
  "cliente Diamante Plus com dívida em aberto"
- A ação deve estar na voz do usuário, não do negócio
- O valor deve refletir o benefício para o usuário — não o objetivo da Bemol disfarçado
### Fluxo resumido
- Usar somente quando houver mais de uma tela **ou** mais de uma chamada de API envolvida
- Passos concisos — não é documentação técnica, é orientação de contexto
### Análise de impacto
- Listar dependências de outros cards pelo ID quando conhecido (ex: [260535])
- Listar objetos afetados no nível que o desenvolvedor precisa para estimar — tabelas SAP,
  endpoints da API BSF, componentes de front
### Fora de escopo
- Incluir apenas quando há risco real de interpretação ampliada
- Exemplos de quando incluir: card que trata só de Pix mas o contexto sugere Boleto também;
  card que trata de exibição mas o contexto sugere que o dev pode tentar implementar a lógica
  de negócio junto
### Critérios de Aceite
- Cada CA deve ser verificável de forma objetiva — comportamento do sistema ou do usuário,
  não tarefa interna do time
- Numeração simples: CA1, CA2, CA3... sem agrupamentos temáticos
- Cobrir: happy path, estados de erro relevantes, edge cases identificados no contexto
- Não incluir CAs que dependam de decisões ainda em aberto — nesses casos, registrar como
  ponto em aberto ao final do card (fora do formato oficial)
---
 
## Referências de contexto
 
- Workspace Notion: **BSF - Cobrança**
- Database de épicos: **Tarefas** (títulos com 👑)
- Épicos de referência do Portal Web:
  - 👑 Portal Renegociação (interno) — ID `353adafb-d762-80a2-82f4-e5a086a7bd45`
  - 👑 CRM de Cobrança — ID `34aadafbd762803aa285f1881a5358b6`
- API de Renegociação BSF: documentada no Manual de Integração ASSESSORIAS v3 (PRD)
  — disponível como arquivo de projeto
- Arquitetura: SAP → Middleware C# → CobranSaaS / API BSF