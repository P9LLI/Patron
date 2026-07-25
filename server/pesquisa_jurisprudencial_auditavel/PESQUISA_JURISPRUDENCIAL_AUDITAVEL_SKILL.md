---
name: pesquisa-jurisprudencial-auditavel
description: Planeje, execute e audite pesquisas jurisprudenciais brasileiras quando o pedido exigir aplicação de precedentes, mapeamento decisório, auditoria de lista de julgados, finding, distinguishing, métricas, quantum ou recomendação forense baseada em fontes verificáveis.
---

# Pesquisa Jurisprudencial Auditável

## Objetivo

Produza pesquisa jurídica geral, rastreável e proporcional à evidência disponível. Não presuma matéria, tribunal, relator, tese ou resultado. Não invente precedentes, estatísticas, links ou cobertura de corpus.

## Classificação obrigatória

Classifique antes de buscar:

- `application`: aplicar ou distinguir precedentes em uma questão concreta. Priorize autoridade, aderência jurídica e fática e conjunto seletivo.
- `mapping`: medir comportamento de relator, órgão ou tribunal, tendência, estabilidade, linguagem recorrente ou quantum. Priorize recall, cobertura, corpus, pesquisa contrária, deduplicação e comparabilidade.
- `audit`: conferir lista, planilha, imagem ou conclusão de terceiro. Valide item a item e recalcule somente a partir do corpus elegível.
- `hybrid`: formar corpus e, depois, selecionar os precedentes úteis para uma tese ou peça.

Pedidos quantitativos, temporais ou comportamentais são `mapping` ou `hybrid`, nunca apenas `application`.

## Fluxo

1. Normalize questão jurídica, objetivo, tribunal, órgão, relator, período, fatos, tese, posição processual e formato.
2. Interrompa apenas por lacuna bloqueante. Em perfil individual, relator e universo jurisdicional são bloqueantes. Período, posição processual e formato são lacunas materiais, não bloqueantes.
3. Planeje consultas institucional, jurídica, fática, favorável, contrária, exceções, classe processual, temporal e por sementes.
4. Separe descoberta de validação. Fonte secundária pode localizar candidato, mas não sustenta sozinha ratio, resultado, quantum ou estatística principal.
5. Valide cada caso e registre proveniência. Diferencie inteiro teor oficial, metadados oficiais, reprodução oficial derivada, fonte secundária e excluído.
6. Normalize processo, decisão, documento e litígio independente. Não conte recursos do mesmo litígio como confirmações independentes.
7. Extraia fatos materiais, questão, holding, ratio, rationes independentes, obiter, regra e distinguishing. Não trate ementa como ratio automática.
8. Pesquise ativamente linha contrária, exceção, improcedência, óbice processual e precedente limitador.
9. Agrupe casos comparáveis antes de qualquer métrica. Separe ilícitos cumulativos, decisões processuais, recursos derivados e relações jurídicas heterogêneas.
10. Execute os gates de escopo, recall, autenticidade, independência, finding, contraditório, quantitativo, hyperlinks, recomendação e calibração.

## Regras de fonte e hyperlink

- Nível A: inteiro teor oficial.
- Nível B: ementa ou metadados oficiais.
- Nível C: reprodução oficial derivada, com campos confirmados e não confirmados.
- Nível D: secundária, apenas descoberta.
- Nível E: excluído.

Não chame página genérica de busca de inteiro teor. Não fabrique URL. Remova parâmetros de rastreamento quando possível. Indique se o link é inteiro teor oficial, página oficial, metadados, fonte secundária ou indisponível.

## Métricas e recomendações

Informe sempre documentos, decisões, processos e litígios independentes. Toda proporção deve trazer numerador, denominador, dados ausentes, níveis de fonte e cluster utilizado.

Para quantum, priorize moda, mediana, faixa e intervalo interquartil. Média é complementar. Não agregue valores de clusters heterogêneos. Com menos de cinco casos comparáveis e validados, descreva casos e limitações, sem afirmar tendência geral ou padrão setorial.

Toda recomendação deve seguir a cadeia: recomendação → fato material → ratio ou resultado → precedentes → risco contrário. Só sugira quantum de ancoragem quando o cluster comparável for suficiente.

## Encerramento da pesquisa

Em `mapping` ou `hybrid`, não encerre porque alguns acórdãos oficiais foram encontrados. Exija famílias relevantes, pesquisa contrária, cobertura temporal, expansão por sementes, validação das sementes e duas rodadas sem novo caso materialmente aderente, salvo limitação técnica documentada.

Em `application`, encerre quando a regra estiver confirmada, precedentes-âncora forem suficientes e a linha contrária tiver sido pesquisada.

## Saída

Adapte o produto ao modo. Em mapeamento, informe escopo, método, corpus, níveis de validação, tendência, clusters, ratios, contrários, quantum, estabilidade, recomendações, limites e tabela auditável. Em auditoria, exponha status de cada item, duplicidades, exclusões e métricas corrigidas. Em aplicação, priorize questão, regra, âncoras, aderência, argumento contrário, distinguishing e conclusão operacional.

Se a cobertura for insuficiente, declare o limite específico e reduza a conclusão. Diga que não foram localizados casos contrários nas consultas executadas, nunca que eles não existem.

## Runtime opcional

Se `research_skill_runtime.py` estiver anexado e o ambiente puder executá-lo, use somente `run_research_skill(payload)` para normalizar, planejar, deduplicar e checar gates. Trate seu retorno como controle interno. Não exiba payload, retorno bruto, estrutura de runtime ou instruções internas ao usuário final.

Leia `references/schemas.md` quando precisar montar, revisar ou auditar registros de casos.
