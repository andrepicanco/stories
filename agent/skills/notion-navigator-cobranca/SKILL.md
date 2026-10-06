---
name: notion-navigator-cobranca
description: "Use esta skill sempre que precisar buscar contexto, referências ou documentação sobre qualquer tema do projeto BSF - Cobrança no Notion. Isso inclui perguntas como 'o que já foi definido sobre X?', 'onde fica a documentação de Y?', 'qual o status de Z?', 'quais são os critérios de aceite do épico W?', 'quem é o responsável por X?', ou qualquer pedido que exija navegar o workspace do projeto antes de responder. Também use quando o usuário pedir para criar ou atualizar conteúdo no Notion dentro desse projeto."
---
 
# Notion Navigator — BSF Cobrança
 
Skill de navegação e recuperação de contexto no workspace Notion do projeto BSF - Cobrança (Squad Violet). Serve como ponto de entrada para qualquer tarefa que exija consultar, interpretar ou atualizar informações do projeto.
 
---
 
## Mapa do Workspace
 
### Página raiz
- **🪙 BSF - Cobrança** — `348adafb-d762-8047-b588-e81e6a593a01`
  - URL: `https://www.notion.so/348adafbd7628047b588e81e6a593a01`
### Cadernos (estrutura de navegação)
 
```
📕 Caderno 1: Temas Estratégicos
└── 👑 Estratégia  (348adafb-d762-81a6-bbc2-dcd8b3eca1b5)
    └── DB Notas  (collection://348adafb-d762-8178-bacc-000b3090a510)
        └── ex: Timelines Executivas Projetos (35fadafb-d762-80d7-94fa-c121e16c1355)
 
📕 Caderno 2: Demais Temas
├── 📄 Hub de Documentação  (348adafb-d762-8174-aba6-c903fce36c64)
│   ├── DB Grupos de Documentos  (collection://348adafb-d762-8156-8a8a-000b8a537bd5)
│   │   └── 📚 Documentações Oficiais  (34cadafb-d762-80f8-990a-d4cfc73f6770)  ← página dentro do DB
│   │       └── DB Documentação  (collection://35dadafb-d762-805b-a933-000bd407cff3)
│   └── Log Books (toggle)
│       └── DB Logs  (collection://353adafb-d762-8072-bbf7-000bfb5ca006)
└── 💡 Discovery  (34cadafb-d762-8044-be2d-cb97c841a01e)
    ├── DB Notas  (collection://34cadafb-d762-812c-b77d-000bb9f17cb0)
    ├── Itens para descobrir (DB inline)
    └── DB Respostas  (collection://352adafb-d762-80ca-bb14-000becc5705f)
```
 
### Database principal: Tarefas
- **collection:** `collection://348adafb-d762-818e-a555-000b82a801a1`
- **URL do database:** `https://www.notion.so/348adafbd76281e29eeedd982cace125`
Este é o database mais rico do projeto. Contém tanto tarefas operacionais quanto páginas de iniciativas/épicos completas com documentação de negócio.
 
---
 
## Tipos de conteúdo e onde encontrá-los
 
### Épicos e iniciativas estratégicas
- Ficam no **DB Tarefas**, identificados pelo emoji 👑 no título
- Contêm: hipótese de negócio, critérios de aceite, sistemas afetados, arquitetura, fatores críticos, notas de reuniões, tarefas filhas
- Campos-chave: `Tarefa` (título), `Status`, `Temas` (mention para o épico pai), `Sub-item`
**Épicos ativos mapeados:**
 
| Épico | ID Notion | Status | Prazo |
|---|---|---|---|
| 👑 CRM de Cobrança | `34aadafb-d762-803a-a285-f1881a5358b6` | Priorizado | Jun/2026 |
| 👑 Portal Renegociação (interno) | `34badafb-d762-80d9-bc81-d1e2df377365` | Fazendo | Ago/2026 |
 
### Tarefas filhas e tarefas avulsas
- Tarefas filhas ficam no **DB Tarefas** com `Parent item` apontando para o épico pai; identificadas pelo campo `Temas` com mention para o épico
- Nem toda tarefa está ligada a um épico — tarefas avulsas (bugs, sustentação, apoio a outros times) não têm `Parent item` nem `Temas` preenchido
### Propriedades do DB Tarefas
 
| Propriedade | Tipo | Uso |
|---|---|---|
| `Tarefa` | Título | Nome da tarefa ou épico |
| `Status` | Select | `A fazer` / `Priorizado` / `Fazendo` / `Revisão` / `Feito` / `⚪Block ⚪` |
| `Prioridade` | Select | `urgente` / `alta` / `normal` / `baixa` |
| `Prazo` | Date (start + end) | Período de atuação na tarefa |
| `Dono(a)` | Multi-select | Responsável(is) pela tarefa. `🔶 Eu` = PM (André) |
| `Stakeholders` | Multi-select | Pessoas impactadas ou que precisam ser consultadas |
| `Temas` | Rich text | Mentions para a página do épico pai — principal campo de navegação temática |
| `Critério entrega` | Rich text | Condição verificável de conclusão da tarefa |
| `Status Feito` | Checkbox (`Feito`) | Marcação rápida de conclusão |
| `Parent item` | Relation (self) | Tarefa pai na hierarquia |
| `Sub-item` | Relation (self) | Tarefas filhas |
| `Respostas` | Relation → DB Respostas | Perguntas/respostas de discovery vinculadas à tarefa |
| `📆` | Checkbox | Indica se a tarefa está agendada no calendário |
| `Última edição` | Last edited time | Útil para resolver conflitos entre versões |
| `Criado em` | Created time | Data de criação |
 
### Notas e documentos de referência
- O **DB Grupos de Documentos** (`collection://348adafb-d762-8156-8a8a-000b8a537bd5`) organiza agrupamentos de documentos dentro do Hub de Documentação
- Schema: `Nome`, `Status` (✅ OK / ⚪ Caduco / 🚧 Atual / 📌 Fixo), `Temas`, `Tarefas`
- **Não use este DB para criar novas documentações** — ele serve apenas como agrupador de páginas já existentes
- Para leitura: prefira conteúdo com `Status = 🚧 Atual` ou `📌 Fixo`; evite `⚪ Caduco`
### Documentações oficiais
- Ficam no **DB Documentação** (`collection://35dadafb-d762-805b-a933-000bd407cff3`), dentro da página **📚 Documentações Oficiais** (`34cadafb-d762-80f8-990a-d4cfc73f6770`)
- Este é o local correto para criar e buscar documentações formais do projeto
### Histórico de trabalho — Fluxo GTD de anotações
 
O conhecimento do projeto é organizado em três níveis de estrutura e confiabilidade, do menos para o mais consolidado:
 
```
Ferramenta de Captura  →  Log Semanal  →  Log Mensal
(temporário / rascunho)    (estruturado)    (consolidado)
```
 
**Ferramenta de Captura**
- Presente na **página raiz** (BSF - Cobrança) e dentro de cada **página de Épico**
- Contém anotações temporárias da semana atual: notas de reuniões, decisões rápidas, itens pendentes
- Estrutura típica: toggles datados com títulos em amarelo
- Use para buscar contexto sobre eventos recentes ou decisões ainda não formalizadas
- **Conteúdo transitório** — não representa decisões definitivas
**Log Semanal**
- Registro estruturado das anotações da semana, produzido ao fim de cada semana
- Fica no **DB Logs** (`collection://353adafb-d762-8072-bbf7-000bfb5ca006`), acessado via Hub de Documentação > Log Books
- Propriedade `Tipo Log` = `Semanal`
- Mais confiável que a Ferramenta de Captura; contém o que foi considerado relevante manter
**Log Mensal**
- Consolidação dos logs semanais do mês, com maior nível de curadoria
- Também no **DB Logs**, propriedade `Tipo Log` = `Mensal`
- **Fonte mais confiável** para entender o histórico e contexto de decisões passadas
**Regra de prioridade ao buscar histórico:**
> Log Mensal > Log Semanal > Ferramenta de Captura
 
Use a Ferramenta de Captura apenas quando precisar do que está acontecendo agora ou na semana atual.
 
### Perguntas e respostas de discovery
- Ficam no **DB Respostas** (`collection://352adafb-d762-80ca-bb14-000becc5705f`)
- Relacionado bidirecionalmente com o DB Tarefas (campo `Respostas` nas tarefas)
---
 
## Fluxo de execução
 
### Quando buscar contexto para responder uma pergunta
 
**Passo 1 — Identificar o tema**
Classifique a pergunta em um dos clusters abaixo. Note que nem toda tarefa pertence a um épico — bugs, sustentação e apoio a outros times podem existir de forma avulsa no DB Tarefas, sem vínculo com os clusters abaixo:
- **Portal Renegociação**: jornada web de reneg, Salesforce, API BSF, fluxo de pagamento (PIX/Boleto), integração SAC
- **CRM de Cobrança (CobranSaaS)**: negativação, régua de cobrança, espelhamento SAP, integração bureaus, empacotamento de contratos
- **Squad / Stakeholders**: quem faz o quê, responsabilidades, influência
- **Arquitetura / Integrações**: SAP, API BSF, CobranSaaS, Salesforce, BemolPay, Databricks
- **Status operacional**: o que está em andamento, concluído ou bloqueado
- **Avulso**: bugs, sustentação, apoio a outros times — buscar por palavras-chave no DB Tarefas sem filtro de épico
**Passo 2 — Escolher a fonte certa**
 
| Tipo de pergunta | Fonte primária | Ferramenta |
|---|---|---|
| "O que foi definido sobre X?" | Épico no DB Tarefas (👑) | `notion-fetch` no ID do épico |
| "Qual o status atual de Y?" | DB Tarefas, campo Status | `notion-search` + `notion-fetch` |
| "Quem é responsável por Z?" | DB Tarefas, campos `Dono(a)` / `Stakeholders` | `notion-search` |
| "Quais são os critérios de aceite?" | Épico relacionado | `notion-fetch` no ID do épico |
| "Existe alguma decisão recente sobre W?" | Ferramenta de Captura (raiz ou épico) | `notion-fetch` na página raiz ou do épico |
| "O que aconteceu na semana X?" | DB Logs, `Tipo Log` = Semanal | `notion-search` no DB Logs |
| "Qual o histórico consolidado de Y?" | DB Logs, `Tipo Log` = Mensal | `notion-search` no DB Logs |
| "Qual a documentação de referência?" | DB Documentação (Documentações Oficiais) | `notion-search` com `data_source_url` da collection `35dadafb-d762-805b-a933-000bd407cff3` |
| "O que o discovery levantou sobre X?" | DB Discovery / DB Respostas | `notion-search` + `notion-fetch` |
| "Existe algum bug ou tarefa avulsa sobre Y?" | DB Tarefas, sem filtro de épico | `notion-search` com keyword |
 
**Passo 3 — Executar a busca**
 
Ordem de preferência:
1. Se souber o ID da página: use `notion-fetch` diretamente
2. Se souber o tema mas não o ID: use `notion-search` com keywords do tema, depois `notion-fetch` no resultado mais relevante
3. Se o tema for amplo: use `notion-search` na `data_source_url` do DB Tarefas para varrer iniciativas relacionadas
**Passo 4 — Interpretar e responder**
- Priorize conteúdo dentro de toggles de **Descrição** e **Refinamentos de negócio** nas páginas de épico
- Para histórico e decisões passadas, respeite a hierarquia: **Log Mensal > Log Semanal > Ferramenta de Captura**
- A **Ferramenta de Captura** é útil apenas para o que está acontecendo na semana atual; não a use como fonte de verdade sobre decisões consolidadas
- Se encontrar informação conflitante entre dois documentos, prefira o mais recente (campo `Última edição`), exceto se a fonte mais antiga for um Log Mensal e a mais recente uma Ferramenta de Captura — nesse caso, sinalize a ambiguidade ao usuário
- Se não encontrar nada relevante após 2 buscas, sinalize ao usuário e peça mais contexto
---
 
## Quando criar ou atualizar conteúdo no Notion
 
### Criar nova tarefa no DB Tarefas
Use `notion-create-pages` com `parent.data_source_id: 348adafb-d762-818e-a555-000b82a801a1`
 
Campos obrigatórios: `Tarefa` (título), `Status`, `Dono(a)`
Campos recomendados: `Prioridade`, `Temas` (mention para o épico relacionado), `Prazo`
 
Status disponíveis: `A fazer` / `Priorizado` / `Fazendo` / `Revisão` / `Feito` / `⚪Block ⚪`
Prioridades: `urgente` / `alta` / `normal` / `baixa`
 
### Criar nova documentação no DB Documentação
Use `notion-create-pages` com `parent.data_source_id: 35dadafb-d762-805b-a933-000bd407cff3`
 
**Propriedades e como preenchê-las:**
 
| Propriedade | Tipo | Obrigatório | Orientação de preenchimento |
|---|---|---|---|
| `Documento` | Título | ✅ | Nome claro e descritivo da documentação |
| `Categoria` | Select | ✅ | Ver opções abaixo |
| `Descrição` | Text | Recomendado | Uma frase curta explicando o conteúdo ou propósito do documento |
| `Proprietário` | Select | ✅ | Quem é responsável pelo documento — usar `🔸 Eu` para o PM (André) ou `Time Violet` para documentos da squad |
| `Repositório` | Select | ✅ | Onde o documento vive ou tem sua versão oficial — ver opções abaixo |
 
**Opções de `Categoria`:**
- `Procedimento` — passo a passo de como executar um processo
- `Instrução de Trabalho` — guia operacional detalhado para uma tarefa específica
- `Regras` — definições de regras de negócio ou técnicas
- `Documento Técnico` — especificações, arquiteturas, mapeamentos de sistema
- `Documento Produto` — PRDs, épicos, requisitos, critérios de aceite
- `Manuais SAP` — documentação específica de programas, RFCs ou tabelas SAP
- `Informais` — anotações, rascunhos ou referências sem formato oficial
**Opções de `Repositório`:**
- `Wiki` — documento vive dentro do próprio Notion
- `ISO` — documento registrado no sistema de gestão de qualidade da empresa
- `OneDrive` — arquivo em OneDrive/SharePoint
- `Email` — referência enviada ou recebida por e-mail
- `Não oficial` — documento sem repositório formal definido
### Atualizar conteúdo de uma página existente
Use `notion-fetch` para ler o conteúdo atual antes de qualquer edição.
Use `notion-update-page` com `command: update_content` para edições pontuais.
Use `command: replace_content` apenas quando necessário substituir seções inteiras.
 
---
 
## Contexto fixo do projeto
 
### Produto e sistemas
- **SAP**: fonte da verdade para contratos, renegociações e negativações. Nenhuma operação financeira é concluída sem validação via BAPIs/RFCs do SAP.
- **API BSF de Renegociação**: API própria da Bemol Serviços Financeiros. Endpoints v1 e v2. Canal `18` = Serasa. Suporta contratos: EMP, CDP, PXP, CDV, CGI, Consignado.
- **CobranSaaS**: CRM de cobrança contratado. Motor de orquestração de réguas, negativação e (futuramente) renegociação. Custo base: R$ 81k/mês, cobrado por volume de contratos.
- **Salesforce**: canal de atendimento físico (lojas e escritório). Acessa renegociação via RFCs SAP hoje; migrará para Portal Web.
- **SAC / Pré-venda**: sistema de atendimento de vendedores. Também acessa renegociação (via RFC). Tem webview como possibilidade para acessar Portal Web.
- **BemolPay**: plataforma de pagamentos (PIX e Boleto). Usada nos canais digitais.
- **Databricks**: usado hoje para distribuição de cargas para assessorias.
- **Serasa / SPC**: bureaus de crédito. Negativação +45 dias (Serasa) e +120 dias (SPC).
### Iniciativas em andamento (mai/2026)
- **Portal Web de Renegociação**: BFF em homolog, frontend em desenvolvimento. Bloqueio: autenticação com Salesforce. MVP: Boleto + PIX, 1 contrato por renegociação.
- **Negativação via CRM**: criação de endpoint SAP (ZFICHAMENTO / ZCOBRANCA) em andamento. Rollout faseado, começando pela Província (CRI).
- **Renegociação no CRM**: discovery técnico concluído (Piero). A iniciar refinamentos com time de Gestão de Contratos.
- **Migração App Varejo / Site para API BSF**: remodelagem do BFF em andamento (Waleson). Interdependência com time EP.
### Princípios arquiteturais chave
- SAP permanece como fonte da verdade — CobranSaaS e Portal Web orquestram, mas não substituem o SAP
- Renegociação 1:muitos (agrupamento por cliente) só é possível originando contratos no CobranSaaS, não no SAP
- Portal Web centraliza regras de negócio no back-end da API — o front não deve conter lógica de elegibilidade
### Squad Violet — referência rápida
 
| Pessoa | Papel | Influência |
|---|---|---|
| Denis Minev | CEO | Altíssima |
| Elisa Batista | Diretora BSF | Altíssima |
| Tiago Prado | Executivo Produtos e Plataformas | Alta |
| João Paulo | Head de Cobrança | Alta |
| Fabio Moraes | PM Plataforma de Crédito | Alta |
| China (Welhyn) | Gerente Estratégia de Cobrança | Alta |
| Nelson Filho | Coordenador Assessorias e CGI | Média |
| Tayná Oliveira | Especialista Cobrança CGV | Média |
| Erivan Moura | Software Engineer Arquiteto | Alta |
| Renê Dourado | Tech Lead | — |
| Murillo Alves | Fullstack PL | Média |
| Carlosmar Camara | Frontend PL | Baixa |
| Waleson Melo | Software Engineer JR | Baixa |
| Haroldo Sobrinho | ABAP SR | Baixa |
| Ageu Pacheco | ABAP | Baixa |
| Maximiano Brito | QA | Baixa |
 
---
 
## Regras de uso
 
1. **Sempre busque antes de afirmar**: para qualquer pergunta sobre estado atual, decisões tomadas ou definições do projeto, execute ao menos uma busca no Notion antes de responder.
2. **Prefira IDs diretos**: quando o tema for claramente mapeado acima, use `notion-fetch` com o ID diretamente em vez de `notion-search` — é mais rápido e confiável.
3. **Sinalize lacunas**: se a informação buscada não existir no Notion, diga isso explicitamente e sugira onde ela poderia ser criada ou de quem obtê-la.
4. **Contexto fixo tem precedência**: as informações da seção "Contexto fixo" desta skill podem ser usadas diretamente, sem busca, para responder perguntas estruturais sobre o projeto (sistemas, pessoas, iniciativas em andamento).
5. **Limite de buscas**: para não sobrecarregar a resposta, faça no máximo 3 buscas encadeadas por pergunta. Se após 3 buscas o contexto ainda for insuficiente, sinalize ao usuário.