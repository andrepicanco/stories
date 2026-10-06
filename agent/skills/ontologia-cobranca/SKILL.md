---
name: ontologia-cobranca
description: "Use esta skill quando a ontologia de Cobrança estiver disponível e o card tratar de qualquer tema do domínio (renegociação, negativação, acordos, parcelas, CobranSaaS, CRM, notificações, regras e fluxos do time Violet). Ela explica como consultar os conceitos, as relações e a cronologia antes de redigir, e como escrever sugestões novas no padrão STE-pt."
---

# Ontologia de Cobrança

A ontologia é um mapa curado do domínio: conceitos, sistemas, repositórios, fluxos, regras e eventos datados. Ela diz **o que as coisas são e como se ligam**. As outras fontes (wiki, Notion, cards) dizem **o que foi decidido ou pedido**.

## Como consultar (antes de redigir)

1. Chame `ontologia_buscar` com o tema do card. Use mais de uma busca se o tema tiver vários termos.
2. Chame `ontologia_conceito` nos 2 ou 3 conceitos centrais. Leia a descrição, as relações e as fontes.
3. Chame `ontologia_vizinhos` para descobrir sistemas, regras e fluxos ligados ao tema. Eles alimentam "Recursos impactados" e os critérios de aceite.
4. Chame `ontologia_linha_do_tempo` quando o card depender de algo recente (implantação, mudança de regra, card em deploy).

## Como usar o que encontrou

- Use sempre o **nome aprovado** do conceito. Nunca escreva os sinônimos listados como "não aprovados".
- Trate como fato só o que **não** vier marcado "NÃO CONFIRMADO".
- Cite no comentário quais conceitos da ontologia você consultou e o que **não** encontrou.
- Se a ontologia contradiz a wiki, o Notion ou um card, **não escolha em silêncio**: registre a divergência no comentário.

## Como escrever sugestões novas

Quando o card revelar um conceito, uma relação ou um fato que a ontologia não tem, descreva-o no padrão **STE-pt**:

- Frases de até 20 palavras (nunca mais de 25), uma ideia por frase.
- Voz ativa, presente do indicativo.
- Um termo por conceito, sem sinônimos.
- Sigla definida na primeira vez: "Nome completo (SIGLA)".
- Sem "etc.", sem sentido figurado.
