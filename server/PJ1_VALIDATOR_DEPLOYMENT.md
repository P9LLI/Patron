# Implanta??o PJ1 Validator v1

## Escopo

Esta implanta??o acrescenta `/v1/pj1/validate` ao servidor existente sem modificar `server/main.py` nem `server/main_pj1.py`.

## Arquivos novos

- `server/main_pj1_validator.py`;
- `server/pj1_validation/`;
- `server/openapi_pj1_validator.json`.

`server/requirements.txt` recebeu apenas `jsonschema==4.24.0`.

## Configura??o obrigat?ria

1. Defina `PJ1_API_BEARER_TOKEN` com segredo aleat?rio de alta entropia. O token pertence ? Action, n?o ao usu?rio.
2. Defina `PJ1_IDEMPOTENCY_DB` em volume persistente. Se omitido, o servi?o reutiliza `DB_PATH`.
3. Mantenha uma ?nica inst?ncia enquanto SQLite for usado. Para m?ltiplas inst?ncias, migre a tabela de idempot?ncia para PostgreSQL ou Redis antes do scale-out.
4. Suba a nova entrada:

```text
uvicorn server.main_pj1_validator:app --host 0.0.0.0 --port 10000
```

5. Importe `server/openapi_pj1_validator.json` na Action e configure autentica??o Bearer com o mesmo token.
6. Nunca solicite o token, OAB, e-mail ou outro identificador ao usu?rio para chamar a rota de valida??o.

## Verifica??es antes do corte

- `GET /health` continua respondendo;
- `/validateSubscription` e `/v14_2/pj1/research-plan` continuam presentes;
- `/v1/pj1/validate` retorna 401 sem token;
- request v?lido retorna response conforme o contrato;
- repeti??o do mesmo payload retorna `X-PJ1-Idempotent-Replay: true`;
- mesma chave com payload diferente retorna 409.

## Rollback

Restaure o comando anterior:

```text
uvicorn server.main_pj1:app --host 0.0.0.0 --port 10000
```

A tabela `pj1_idempotency` pode permanecer no banco: as entradas anteriores n?o a utilizam.

## Bloqueios remanescentes

- host e segredos reais n?o s?o armazenados no reposit?rio;
- `PJ1-REG-REAL-CADIN-002` aguarda metadados auditados;
- a conex?o ao Custom GPT exige duas rodadas consecutivas com P1=P2=P3=P4=0.
