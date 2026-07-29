# Ambiente de testes — GPT Workflow v1

- Python: 3.13 no ambiente local de validação.
- Persistência: SQLite temporário exclusivo por teste, com `foreign_keys=ON`, WAL e `synchronous=FULL`.
- Web framework: versões já fixadas em `server/requirements.txt`; nenhuma dependência nova foi adicionada.
- Disco: percentuais de 70%, 85% e 95% simuláveis por `GPT_WORKFLOW_SIMULATED_DISK_PERCENT`.
- Autenticação: Bearer token de teste, separado do `PJ1_API_BEARER_TOKEN`.
- Isolamento: os testes não abrem nem modificam `server_data.db`.

Comandos:

```text
python -m unittest server.gpt_workflow.tests.test_workflow_service -v
python -m unittest discover -s server/tests -v
python -m unittest discover -s server/pesquisa_jurisprudencial_auditavel/tests -v
```

No ambiente Codex para Windows, o diretório temporário deve estar dentro de uma raiz gravável. Isso não afeta a execução normal nem o Render.
