# Policy: Session Timing and Limits

## Session timing
- Session tokens expire quickly (default 10 minutes).
- Expired token => revalidate before any action.

## Revalidation frequency
- Revalidate on every execution.
- Do not reuse old tokens across turns.

## Rate limiting
- Enforce a maximum number of executions per user per time window.
- If limit exceeded, respond with the block message.

## Turn and token limits
- Keep responses concise and final.
- Do not perform multi-turn chaining without revalidation.
- If the user attempts to force long multi-part extraction, block and require revalidation.
