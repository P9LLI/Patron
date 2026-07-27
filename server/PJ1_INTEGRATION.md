# Integração PJ1 no PATRON v14.2

## Resultado

A v14.2 permanece preservada. `server/main.py` e
`patron/runtime_public/patron_runtime.py` não foram modificados. A extensão é
composta por:

- `server/patron_pj1_adapter.py`: combina a saída intacta da v14.2 com os
  controles PJ1.
- `server/main_pj1.py`: importa a aplicação original e acrescenta a rota
  protegida `/v14_2/pj1/research-plan`.
- `server/openapi_pj1.yaml`: schema a importar na Action do Custom GPT.
- `server/pesquisa_jurisprudencial_auditavel/`: runtime, instruções, schemas,
  fixtures e testes do PJ1.

## Contratos

O runtime legado recebe somente:

```json
{"q":"...","tt":"jurisprudencia","tr":["TJSP"],"pd":"...","cx":"...","of":"...","m":"p1"}
```

O PJ1 recebe seu próprio objeto, sem campos novos no runtime legado:

```json
{"research_mode":"mapping","legal_question":"...","known_cases":[]}
```

O adaptador chama a v14.2 primeiro. Se ela rejeitar a entrada ou pedir fatos,
o PJ1 não é acionado. Quando acionado, fica no bloco `pj1` da resposta e não
altera o conteúdo de `v142`.

## Implantação no Render

1. Preserve o build existente:

```bash
pip install -r server/requirements.txt
```

2. Altere somente a entrada da aplicação:

```bash
uvicorn server.main_pj1:app --host 0.0.0.0 --port 10000
```

3. Preserve todas as variáveis de ambiente e o banco de dados existentes.
4. Valide `/health`, `/validateSubscription` e
   `/v14_2/pj1/research-plan`.

## Configuração do Custom GPT

1. Substitua o schema da Action por `server/openapi_pj1.yaml`.
2. Mantenha o fluxo de acesso e acrescente o conteúdo de
   `pesquisa_jurisprudencial_auditavel/gpt_instruction_addendum_pj1.txt` ao
   final das Instructions.
3. Em Knowledge, mantenha `PESQUISA_JURISPRUDENCIAL_AUDITAVEL_SKILL.md`,
   `schemas.md` e `patron_runtime.py`.
4. Remova `research_skill_runtime.py` do Knowledge. Ele passa a ser executado
   no servidor, dentro do adaptador.

## Limite funcional deliberado

A rota PJ1 constrói plano, controla corpus e audita dados fornecidos. Ela não
faz coleta autônoma de julgados nem inventa citações. A busca deve usar fontes
oficiais e o Web Search do GPT; os achados podem voltar no campo `known_cases`
para deduplicação, métricas e gates.


## Extens?o determin?stica v1

A entrada opcional `server.main_pj1_validator:app` importa toda a aplica??o PJ1 anterior e acrescenta `/v1/pj1/validate`. A rota usa Bearer token de servi?o e tabela SQLite separada; consulte `server/PJ1_VALIDATOR_DEPLOYMENT.md`.
