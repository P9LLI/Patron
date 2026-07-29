# Catálogo de erros — GPT Workflow v1

Todos os erros próprios da camada usam `error`, `message` e `retryable`. Erros de autenticação emitidos pelo FastAPI permanecem sob `detail`.

| Código | HTTP | Significado |
|---|---:|---|
| `SERVICE_TOKEN_NOT_CONFIGURED` | 503 | O segredo da nova camada não foi configurado. |
| `INVALID_SERVICE_TOKEN` | 401 | Bearer token ausente ou inválido. |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | Operação mutável sem chave válida. |
| `IDEMPOTENCY_CONFLICT` | 409 | A mesma chave foi reutilizada com payload diferente. |
| `PAYLOAD_TOO_LARGE` | 413 | Request ou draft excede o limite. |
| `CANDIDATE_STORAGE_LIMIT` | 413 | Ficha, trecho ou quantidade de trechos excede o limite. |
| `EXECUTION_STORAGE_LIMIT` | 413 | Limite de bytes ou candidatos da execução seria excedido. |
| `REPOSITORY_VERSION_LIMIT` | 409 | Limite de versões do repositório atingido. |
| `DISK_HARD_LIMIT_REACHED` | 507 | Escrita expansiva bloqueada por uso de disco. |
| `EXECUTION_NOT_FOUND` | 404 | Execução inexistente. |
| `REPOSITORY_NOT_FOUND` | 404 | Repositório inexistente. |
| `BATCH_NOT_FOUND` | 404 | Lote inexistente. |
| `INVALID_STATE_TRANSITION` | 409 | Operação fora da ordem da máquina de estados. |
| `DISCOVERY_INCOMPLETE` | 409 | Tentativa de registrar candidato antes da descoberta. |
| `DISCOVERY_CLOSED` | 409 | Tentativa de alterar consultas após a descoberta. |
| `REPOSITORY_NOT_FROZEN` | 409 | Seleção solicitada sem freeze. |
| `EMPTY_REPOSITORY` | 409 | Freeze de repositório vazio. |
| `BATCH_REPOSITORY_MISMATCH` | 409 | Lote não pertence à versão informada. |
| `SELECTION_INCOMPLETE` | 422 | Avaliações não cobrem exatamente o lote. |
| `SELECTION_EVIDENCE_REQUIRED` | 422 | Avaliação sem razão ou evidência. |
| `FINALIST_NOT_VERIFIED` | 409 | Item principal não foi verificado. |
| `MAIN_RELATOR_NOT_CONFIRMED` | 409 | Item principal sem relator confirmado. |
| `SAMPLE_BLOCKED` | 409 | Claims solicitados sem amostra admitida. |
| `CLAIMS_INCOMPLETE` | 409 | Draft submetido antes da resolução dos claims. |
| `CLAIM_EVIDENCE_REQUIRED` | 422 | Claim suportado/contextual sem evidência. |
| `REPOSITORY_MISMATCH` | 409 | Corpo aponta para repositório ou versão divergente. |
| `CANDIDATE_NOT_IN_REPOSITORY` | 422 | Candidato não pertence ao corpus congelado. |
| `DRAFT_CHANGED_AFTER_RELEASE` | 409 | Tentativa de mudar texto já liberado. |

Findings de auditoria, retornados em `violations`, incluem `UNREGISTERED_CLAIM`, `CLAIM_SCOPE_VIOLATION`, `UNAUTHORIZED_PROCESS`, `UNAUTHORIZED_AMOUNT`, `UNAUTHORIZED_DATE`, `UNAUTHORIZED_SUMULA`, `UNAUTHORIZED_TREND` e `CONTEXT_USED_AS_SAMPLE`.
