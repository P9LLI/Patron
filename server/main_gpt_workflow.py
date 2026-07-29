"""Additive PATRON entrypoint with the isolated GPT workflow API.

The legacy modules are imported unchanged. Rollback consists only of restoring
the previous Render start command: ``server.main_pj1_validator:app``.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse

from server.gpt_workflow.errors import WorkflowError
from server.gpt_workflow.router import router
from server.main_pj1_validator import app


@app.exception_handler(WorkflowError)
async def handle_gpt_workflow_error(_: Request, exc: WorkflowError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.body())


app.include_router(router)
