"""Workflow template API endpoints — CRUD + lifecycle."""

from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.models.workflow import WorkflowStatus
from app.schemas.user import UserResponse
from app.schemas.workflow import (
    WorkflowCreate,
    WorkflowListResponse,
    WorkflowResponse,
    WorkflowSummary,
    WorkflowUpdate,
)
from app.services.workflow_service import WorkflowService

router = APIRouter(
    prefix="/workflows",
    tags=["workflows"],
    dependencies=[Depends(get_current_user)],
)


# ── Helpers ──


def _doc_to_full_response(doc: dict) -> WorkflowResponse:
    """Convert a raw MongoDB document to full WorkflowResponse."""
    nodes = doc.get("nodes", [])
    return WorkflowResponse(
        id=doc["_id"],
        name=doc["name"],
        description=doc.get("description", ""),
        status=WorkflowStatus(doc.get("status", "draft")),
        version=doc.get("version", 1),
        nodes=[_node_to_response(n) for n in nodes],
        edges=[_edge_to_response(e) for e in doc.get("edges", [])],
        tags=doc.get("tags", []),
        created_by=doc.get("created_by", ""),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _doc_to_summary(doc: dict) -> WorkflowSummary:
    """Convert a raw MongoDB document to compact WorkflowSummary."""
    nodes = doc.get("nodes", [])
    return WorkflowSummary(
        id=doc["_id"],
        name=doc["name"],
        description=doc.get("description", ""),
        status=WorkflowStatus(doc.get("status", "draft")),
        version=doc.get("version", 1),
        node_count=len(nodes),
        tags=doc.get("tags", []),
        created_by=doc.get("created_by", ""),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


def _node_to_response(node: dict) -> dict:
    if isinstance(node, dict):
        return {
            "node_id": node.get("node_id", ""),
            "type": node.get("type", "start"),
            "label": node.get("label", ""),
            "config": node.get("config", {}),
            "position": node.get("position", {"x": 0, "y": 0}),
        }
    return {"node_id": "", "type": "start", "label": "", "config": {}, "position": {"x": 0, "y": 0}}


def _edge_to_response(edge: dict) -> dict:
    if isinstance(edge, dict):
        return {
            "edge_id": edge.get("edge_id", ""),
            "source": edge.get("source", ""),
            "target": edge.get("target", ""),
            "label": edge.get("label", ""),
            "condition": edge.get("condition"),
        }
    return {"edge_id": "", "source": "", "target": "", "label": "", "condition": None}


# ── Endpoints ──


@router.post(
    "",
    response_model=WorkflowResponse,
    status_code=201,
    summary="Create a new Workflow template",
)
async def create_workflow(
    body: WorkflowCreate,
    current_user: UserResponse = Depends(get_current_user),
) -> WorkflowResponse:
    """Create a new Workflow template in draft status."""
    doc = await WorkflowService.create(
        name=body.name,
        description=body.description,
        tags=body.tags,
        created_by=current_user.id,
    )
    return _doc_to_full_response(doc)


@router.get(
    "",
    response_model=WorkflowListResponse,
    summary="List Workflow templates",
)
async def list_workflows(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = Query(default=None),
    name: str | None = Query(default=None),
) -> WorkflowListResponse:
    """List Workflow templates with optional filtering."""
    status_enum = WorkflowStatus(status) if status else None
    items, total = await WorkflowService.list(
        page=page,
        page_size=page_size,
        status=status_enum,
        name=name,
    )
    return WorkflowListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_doc_to_summary(d) for d in items],
    )


@router.get(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Get Workflow template detail",
)
async def get_workflow(workflow_id: str) -> WorkflowResponse:
    """Get full Workflow template detail including nodes and edges."""
    doc = await WorkflowService.get_or_404(workflow_id)
    return _doc_to_full_response(doc)


@router.put(
    "/{workflow_id}",
    response_model=WorkflowResponse,
    summary="Update Workflow template",
)
async def update_workflow(
    workflow_id: str,
    body: WorkflowUpdate,
) -> WorkflowResponse:
    """Update a Workflow template (name, description, nodes, edges, tags)."""
    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    # Pydantic v2 model_dump() 已递归序列化嵌套模型为 dict，无需再次转换
    doc = await WorkflowService.update(workflow_id, updates)
    return _doc_to_full_response(doc)


@router.delete(
    "/{workflow_id}",
    status_code=204,
    summary="Delete a Workflow template",
)
async def delete_workflow(workflow_id: str) -> None:
    """Delete a Workflow template."""
    await WorkflowService.delete(workflow_id)


@router.post(
    "/{workflow_id}/publish",
    response_model=WorkflowResponse,
    summary="Publish a Workflow template",
)
async def publish_workflow(workflow_id: str) -> WorkflowResponse:
    """Publish a Workflow template (draft → published)."""
    doc = await WorkflowService.publish(workflow_id)
    return _doc_to_full_response(doc)


@router.post(
    "/{workflow_id}/archive",
    response_model=WorkflowResponse,
    summary="Archive a Workflow template",
)
async def archive_workflow(workflow_id: str) -> WorkflowResponse:
    """Archive a Workflow template (published → archived)."""
    doc = await WorkflowService.archive(workflow_id)
    return _doc_to_full_response(doc)


@router.post(
    "/{workflow_id}/validate",
    summary="Validate Workflow template structure",
)
async def validate_workflow(workflow_id: str) -> dict:
    """Validate a Workflow template without executing it.

    Performs static analysis to detect:
    - DAG structure issues (cycles, orphan nodes, missing start/end)
    - Invalid variable references ({{node.field}} syntax)
    - Missing required node configuration fields
    - Potential circular calls between Agent and Workflow

    Returns validation result with errors, warnings, and info messages.
    """
    from app.engine.workflow.validator import validate_workflow_async
    from app.services.workflow_service import WorkflowService

    doc = await WorkflowService.get_or_404(workflow_id)
    result = await validate_workflow_async(doc)

    return {
        "workflow_id": workflow_id,
        "is_valid": result.is_valid,
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
        "issues": [
            {
                "severity": issue.severity.value,
                "code": issue.code,
                "message": issue.message,
                "node_id": issue.node_id,
                "context": issue.context,
            }
            for issue in result.issues
        ],
    }


@router.post(
    "/validate",
    summary="Validate Workflow template structure (inline)",
)
async def validate_workflow_inline(body: WorkflowCreate) -> dict:
    """Validate a Workflow template before creating it.

    Same as POST /{workflow_id}/validate but accepts the workflow
    definition inline instead of loading from database.
    """
    from app.engine.workflow.validator import WorkflowValidator

    # Build a temporary workflow doc from the request body
    workflow_doc = {
        "_id": "",
        "name": body.name,
        "description": body.description,
        "nodes": [n.model_dump() for n in body.nodes] if body.nodes else [],
        "edges": [e.model_dump() for e in body.edges] if body.edges else [],
    }

    validator = WorkflowValidator(workflow_doc)
    result = validator.validate()  # Sync only — no DB access for inline

    return {
        "workflow_id": None,
        "is_valid": result.is_valid,
        "error_count": len(result.errors),
        "warning_count": len(result.warnings),
        "issues": [
            {
                "severity": issue.severity.value,
                "code": issue.code,
                "message": issue.message,
                "node_id": issue.node_id,
                "context": issue.context,
            }
            for issue in result.issues
        ],
    }

