# GPT Workflow v1

Camada aditiva e isolada para persistir, congelar e auditar o fluxo jurisprudencial em duas passagens. Não busca na web, não chama OpenAI, não executa LLM e não produz análise jurídica.

## Implantação

Use o entrypoint:

```text
uvicorn server.main_gpt_workflow:app --host 0.0.0.0 --port 10000
```

Rollback:

```text
uvicorn server.main_pj1_validator:app --host 0.0.0.0 --port 10000
```

Configure `GPT_WORKFLOW_DATA_DIR` para o mount persistente do Render ou defina diretamente `GPT_WORKFLOW_DB` e `GPT_WORKFLOW_LOG`. Defina um segredo novo em `GPT_WORKFLOW_API_BEARER_TOKEN`. Mantenha uma única instância enquanto SQLite for usado.

## Variáveis

- `GPT_WORKFLOW_DATA_DIR`
- `GPT_WORKFLOW_DB`
- `GPT_WORKFLOW_LOG`
- `GPT_WORKFLOW_API_BEARER_TOKEN`
- `GPT_WORKFLOW_CANDIDATE_MAX_BYTES`
- `GPT_WORKFLOW_EXCERPT_MAX_BYTES`
- `GPT_WORKFLOW_EXCERPTS_MAX_COUNT`
- `GPT_WORKFLOW_REQUEST_MAX_BYTES`
- `GPT_WORKFLOW_DRAFT_MAX_BYTES`
- `GPT_WORKFLOW_EXECUTION_MAX_BYTES`
- `GPT_WORKFLOW_CANDIDATES_MAX_COUNT`
- `GPT_WORKFLOW_REPOSITORY_VERSIONS_MAX`
- `GPT_WORKFLOW_BATCH_SIZE`
- `GPT_WORKFLOW_LOG_MAX_BYTES`
- `GPT_WORKFLOW_LOG_BACKUP_COUNT`
- `GPT_WORKFLOW_TEMPORARY_RETENTION_DAYS`
- `GPT_WORKFLOW_FINALIZED_RETENTION_DAYS`
- `GPT_WORKFLOW_IDEMPOTENCY_RETENTION_DAYS`
- `GPT_WORKFLOW_DISK_WARNING_PERCENT`
- `GPT_WORKFLOW_DISK_RESTRICTED_PERCENT`
- `GPT_WORKFLOW_DISK_CRITICAL_PERCENT`

`GPT_WORKFLOW_SIMULATED_DISK_PERCENT` existe somente para testes controlados e não deve ser definido em produção.

## Contratos

Os artefatos de handoff ficam em `server/gpt_workflow/contracts/`. O `openapi.yaml` ali é próprio da integração e não substitui nem modifica os schemas legados.
