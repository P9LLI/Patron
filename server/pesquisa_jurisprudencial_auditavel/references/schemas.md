# Schemas públicos da skill

## Solicitação normalizada

| Campo | Uso |
|---|---|
| `query` | pedido original resumido |
| `work_type` | jurisprudência, petição, parecer, relatório, memoriais ou minuta |
| `research_mode` | application, mapping, audit ou hybrid, se já definido |
| `tribunals` | tribunais ou órgãos que delimitam o universo |
| `rapporteurs` | relatores quando houver perfil individual |
| `period` | recorte temporal |
| `facts` | fatos ou padrão fático material |
| `legal_question` | pergunta jurídica a resolver |
| `thesis` | tese ou objetivo prático |
| `process_position` | classe, recurso ou posição processual |
| `output_format` | formato desejado |
| `known_cases` | sementes ou registros a auditar |
| `requested_metrics` | tendência, quantum, estabilidade ou outra métrica |
| `executed_families` | famílias já executadas para controle de saturação |

## Registro de caso

| Grupo | Campos mínimos |
|---|---|
| Identificação | `document_id`, `decision_id`, `process_number`, `litigation_id`, `tribunal`, `court_panel`, `rapporteur`, datas, `decision_type` |
| Fonte | `source_level`, `source_url`, `link_kind`, `citation_relation`, `citation_source`, `confirmed_fields`, `unconfirmed_fields`, `provenance`, `confidence` |
| Escopo | `material_topic`, `material_facts`, `legal_question`, `process_position` |
| Resultado | `outcome`, `quantum_origin`, `quantum_final`, `merits` |
| Finding | `holding`, `ratio`, `obiter`, `applied_rule`, `distinguishing` |
| Comparabilidade | `cluster`, `comparability`, `cumulative_harms`, `include_in_statistics`, `exclusion_reason` |

## Valores controlados

| Campo | Valores |
|---|---|
| `source_level` | `official_full_text` ou A; `official_metadata` ou B; `official_derived` ou C; `secondary` ou D; `excluded` ou E |
| `link_kind` | `official_full_text`, `official_case_page`, `official_metadata`, `secondary`, `unavailable` |
| `outcome` | `favorable`, `contrary`, `mixed`, `neutral`, `unknown` |
| `comparability` | `high`, `medium`, `low`, `unknown` |

## Regras de inclusão estatística

O corpus principal usa, por padrão, decisões de mérito dos níveis A ou B, com uma unidade por litígio independente. Registros C e D continuam no corpus ampliado, mas ficam fora da estatística principal salvo confirmação adicional. A saída deve conservar a razão de toda exclusão.
