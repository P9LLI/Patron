"""Isolated deterministic workflow for GPT-supplied legal research."""

from .config import WorkflowConfig
from .service import WorkflowService

__all__ = ["WorkflowConfig", "WorkflowService"]
