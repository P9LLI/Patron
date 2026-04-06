# Migration Notes (Legacy to patron)

This file documents how legacy materials were consolidated into the `patron` skill.

## Legacy sources
- PRIMEIRA VERSAO\Voce e um assistente especializado.txt
- PRIMEIRA VERSAO\REGRAS PARA EVITAR DOWNLOAD EM CUSTOM GPT.txt
- SEGUNDA VERSAO\SKILL (5).md
- SEGUNDA VERSAO\politica_respostas_suppress_logs_v2 (1).md
- CUSTOM-GPT-SYSTEM PROMPT NFRB-NS-SNS LEGAL FRAMEWORK ADVANCED v12 - FINAL STRUCTURE.txt

## Key changes
- Removed Knowledge dependency. All IP is delivered via Actions.
- Removed Code Interpreter and embedded algorithm code.
- Converted numerical steps to qualitative heuristics.
- Consolidated suppression rules into `politica_supressao.md`.
- Added explicit Actions anti-exfiltration rules.
- Added session timing, rate limits, and revalidation requirements.

## Current canonical files
- `SKILL.md`
- `references/framework_v12_adaptado.md`
- `references/politica_supressao.md`
- `references/politica_actions_anti_extracao.md`
- `references/politica_sessao_e_limites.md`
- `references/protocolo_saidas.md`
- `assets/template_saida.md`
