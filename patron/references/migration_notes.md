# Migration Notes (Legacy to patron)

This file documents the migration history only.

## Current target architecture
- v14 Split-Knowledge
- Access validation by Action
- Operational fields returned by the server: `status`, `session_token`, `cfg`, `sk`
- Protected Python runtime attached to the GPT and executed through Code Interpreter

## Historical note
Older drafts mentioned:
- action-delivered algorithm parts
- removal of Code Interpreter
- server-side processing through a separate LLM call

Those variants are not the canonical deployment target for the current repository state.

## Current canonical files
- `server/main.py`
- `server/openapi.yaml`
- `server/gpt_instructions_v14_partA.txt`
- `patron/SKILL.md`
