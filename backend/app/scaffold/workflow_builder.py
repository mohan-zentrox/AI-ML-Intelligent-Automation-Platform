"""
SCAFFOLD ONLY - No-code workflow builder.

Reference: FRD section 6 "No-Code Workflow Builder" (Workflow Builder role,
T6-BE1 owns the backend contract). Intended to let a Workflow Builder role
compose ingestion -> classification -> extraction -> RAG steps as a DAG
without writing code, similar in spirit to Zapier/n8n but scoped to this
platform's document-intelligence primitives.

Nothing here is implemented or wired into the API yet.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorkflowStep:
    """TODO(FRD 6.1): a single node in a workflow DAG.

    step_type would be one of: "ingest", "classify", "extract", "query",
    "review_gate", "webhook". `config` is step-specific JSON config.
    """

    id: str
    step_type: str
    config: dict


@dataclass
class WorkflowDefinition:
    """TODO(FRD 6.2): a full workflow graph (steps + edges) plus versioning
    metadata, persisted to a `workflows` table (not yet modeled) and owned
    by the Workflow Builder role (see app.core.security.Role.WORKFLOW_BUILDER).
    """

    id: str
    name: str
    steps: list[WorkflowStep]
    edges: list[tuple[str, str]]  # (from_step_id, to_step_id)


def execute_workflow(definition: WorkflowDefinition, trigger_payload: dict) -> dict:
    """TODO(FRD 6.3): topologically execute `definition`'s DAG, routing each
    step's output into the next step's input, with per-step error handling
    and a run-history record for observability.
    """
    raise NotImplementedError("No-code workflow execution is scaffolded - see FRD 6.3")
