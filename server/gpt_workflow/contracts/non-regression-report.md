# Relatório de não regressão

Data: 2026-07-29
Escopo: `PATRON_REPO_DEPLOY/server`

## Inventário preservado

- `server/main.py`: FastAPI legado, SQLite legado, Stripe, cadastro, assinatura, bloqueio e webhook.
- `server/main_pj1.py`: extensão de plano PJ1.
- `server/main_pj1_validator.py`: validação determinística PJ1 e idempotência.
- `server/server_data.db` e tabelas legadas: não abertos pelos testes novos e não alterados.
- schemas OpenAPI legados, requirements, logs, autenticação e rotas existentes: não modificados.

`git diff --name-only` não apresentou arquivo rastreado anterior modificado. A entrega contém somente `server/main_gpt_workflow.py` e o novo namespace `server/gpt_workflow/`.

## Testes novos

Resultado final: **25 aprovados, 0 falhas**.

- 12 testes do serviço e da máquina de estados;
- 4 testes de armazenamento, rollback e rotação;
- 1 teste de aceite ponta a ponta com bloqueio seguido de liberação contextual;
- 4 testes de contratos, referências, autenticação e idempotência;
- 3 testes HTTP de health, autenticação, replay e preservação da aplicação importada;
- 1 teste de reconstrução de batch a partir de documento normalizado e vínculo de versão.

Após o último ajuste de deduplicação, os 22 testes não HTTP foram repetidos: **22 aprovados, 0 falhas**. O ajuste não atingiu o roteamento; os 3 testes HTTP já haviam sido aprovados.

## Testes existentes

As suítes existentes foram executadas em processos isolados, porque `test_main_pj1_route.py` injeta intencionalmente stubs em `sys.modules` e não os remove; em descoberta conjunta, isso contamina o módulo FastAPI do teste seguinte. Em processos isolados, que eliminam essa interferência do harness:

- `server.tests.test_main_pj1_route`: 1 aprovado;
- `server.tests.test_main_pj1_validator_route`: 3 aprovados;
- `server.tests.test_openapi_pj1_validator`: 3 aprovados;
- `server.tests.test_patron_pj1_adapter`: 4 aprovados;
- `server.tests.test_runtime_mode`: 2 aprovados;
- `server/pesquisa_jurisprudencial_auditavel/tests`: 4 aprovados.

Total legado: **17 aprovados, 0 falhas**.

## Evidências funcionais

- rotas importadas continuam disponíveis no novo entrypoint;
- nova rota exige Bearer próprio e operações mutáveis exigem `Idempotency-Key`;
- mesmo payload/chave reproduz a resposta; payload divergente é bloqueado;
- transações interrompidas revertem integralmente e `PRAGMA integrity_check` retorna `ok`;
- candidato duplicado reaproveita conteúdo e preserva vínculos com consultas;
- versão congelada permanece imutável e candidato posterior cria versão nova;
- reads continuam disponíveis a 87% de uso simulado; novas escritas expansivas são bloqueadas;
- limpeza preserva receipts e uma tabela não pertencente ao namespace;
- cenário com processos, valores, súmula e tendência não autorizados mantém `answer_release=0`;
- ressubmissão estritamente contextual libera `answer_release=1`.

## Conclusão

A camada é aditiva no código e nos dados. O único passo operacional de ativação é trocar o start command para `server.main_gpt_workflow:app`; o rollback restaura `server.main_pj1_validator:app`.
