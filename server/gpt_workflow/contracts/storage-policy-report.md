# Relatório da política de armazenamento

## Escopo e dados

A camada armazena fichas estruturadas, URLs, identificadores, hashes, trechos curtos, referências de páginas, estados, seleções, verificações, amostra, claims, drafts, resultados de auditoria, receipts e eventos resumidos. Não armazena PDFs, HTML integral, screenshots, respostas integrais de páginas nem arquivos temporários permanentes.

Documentos normalizados ficam em `gptwf_documents` uma única vez por SHA-256. Vínculos com consultas e versões são relacionais; o freeze calcula hash de manifesto sem copiar conteúdo documental.

## Limites padrão

| Item | Padrão |
|---|---:|
| Ficha de candidato | 64 KiB |
| Trecho | 8 KiB |
| Trechos por candidato | 8 |
| Request | 512 KiB |
| Draft | 128 KiB |
| Execução | 50 MiB |
| Candidatos por execução | 5.000 |
| Versões por repositório | 10 |
| Batch | 15 candidatos, limitado a 5–25 |
| Log ativo | 5 MiB |
| Backups de log | 3 |
| Retenção temporária | 7 dias |
| Retenção finalizada | 90 dias |
| Idempotência | 30 dias |

Todos são configuráveis por variáveis prefixadas com `GPT_WORKFLOW_`; a relação completa está no README da camada.

## Retenção, limpeza e auditoria mínima

Dados ativos não são elegíveis para limpeza. Execuções `EXPIRED` ou `TEMPORARY` que já não estejam em andamento podem perder candidatos, lotes, seleções, verificações, amostra, claims e drafts. Receipts, hashes da execução, releases, eventos e o tombstone da exclusão permanecem; a execução passa a `AUDIT_MINIMUM`. A limpeza usa exclusivamente tabelas `gptwf_*`.

Chaves de idempotência expiradas são removidas. Documentos sem referência são eliminados após a limpeza. Cada operação gera log resumido sem payload, segredo ou draft.

## Logs

O logger é independente do legado, rotacionado por tamanho e registra somente tipo de evento, `execution_id`, estados, contagens e hashes. Não registra credenciais, fichas completas nem drafts.

## Disco

- abaixo de 70%: `ok`;
- 70% ou mais: `warning`, registra alerta;
- 85% ou mais: `restricted`, bloqueia novas execuções e candidatos;
- 95% ou mais: `critical`.

Em `restricted`/`critical`, continuam permitidos health, leitura de execução, leitura de release e limpeza.

## Estimativa

Com ficha média normalizada de 12 KiB e aproximadamente 2 KiB de vínculos, estados e índices por candidato:

| Candidatos | Estimativa |
|---:|---:|
| 100 | 1,4–2,0 MiB |
| 1.000 | 14–20 MiB |
| 10.000 | 140–200 MiB |

SQLite, WAL temporário, drafts, evidências maiores e fragmentação podem elevar o consumo. O limite padrão de 5.000 candidatos por execução impede uma única execução de alcançar 10.000 sem reconfiguração explícita.

## Limitações conhecidas

- SQLite pressupõe uma única instância gravadora no Render.
- O uso de disco é medido no filesystem que contém `GPT_WORKFLOW_DB`; o banco deve apontar para o volume persistente.
- A auditoria textual é determinística e conservadora; não faz NER jurídico ou análise semântica.
- O agendamento periódico de limpeza pertence à configuração operacional do Render; existe também endpoint autenticado para execução controlada.

## Testes executados

- 25 testes novos aprovados: unidade, persistência, contratos, cenários de aceite, materialização de lotes e integração HTTP.
- 17 testes legados aprovados em processos isolados, sem regressão observada nas rotas existentes.
- Os detalhes e a ressalva sobre isolamento do harness legado estão em `non-regression-report.md`.
