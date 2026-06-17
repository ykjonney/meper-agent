"""Tests for WorkflowService._validate_for_publish and publish validation."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services.workflow_service import WorkflowService

# ── Fixtures ──


@pytest.fixture(autouse=True)
def mock_database():
    """Mock the MongoDB database for all tests."""
    mock_db = MagicMock()
    with patch("app.services.workflow_service.get_database", return_value=mock_db):
        yield mock_db


def _make_workflow_doc(
    nodes=None,
    edges=None,
    status="draft",
    version=1,
    name="Test Workflow",
):
    """Helper to create a workflow document for testing."""
    return {
        "_id": "wf_test123",
        "name": name,
        "description": "",
        "status": status,
        "version": version,
        "nodes": nodes or [],
        "edges": edges or [],
        "tags": [],
        "created_by": "user_test",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


def _make_start_node():
    return {
        "node_id": "node_start",
        "type": "start",
        "label": "开始",
        "config": {"input_schema": {"type": "object", "properties": {}}},
        "position": {"x": 50, "y": 250},
    }


def _make_end_node():
    return {
        "node_id": "node_end",
        "type": "end",
        "label": "结束",
        "config": {"output_mapping": {}},
        "position": {"x": 600, "y": 250},
    }


def _make_agent_node(agent_id="agent_123", input_query="{{input.query}}"):
    return {
        "node_id": "node_agent",
        "type": "agent",
        "label": "Agent",
        "config": {
            "agent_id": agent_id,
            "input_query": input_query,
            "input_prompt": "{{input.query}}",
            "temperature": 0.7,
        },
        "position": {"x": 300, "y": 250},
    }


def _make_tool_node(tool_id="tool_123"):
    return {
        "node_id": "node_tool",
        "type": "tool",
        "label": "工具",
        "config": {
            "tool_id": tool_id,
            "params": {},
            "timeout_ms": 30000,
        },
        "position": {"x": 300, "y": 400},
    }


def _make_gateway_node(conditions=None, empty=False):
    return {
        "node_id": "node_gateway",
        "type": "gateway",
        "label": "网关",
        "config": {
            "conditions": [] if empty else (conditions or [{"expression": "true", "target": "node_end"}]),
            "default_branch": "node_end",
        },
        "position": {"x": 400, "y": 300},
    }


def _make_human_node(title="审批"):
    return {
        "node_id": "node_human",
        "type": "human",
        "label": "人工审批",
        "config": {
            "title": title,
            "description": "",
            "options": [],
            "timeout_minutes": 60,
        },
        "position": {"x": 350, "y": 350},
    }


def _make_edge(edge_id, source, target, label=""):
    return {
        "edge_id": edge_id,
        "source": source,
        "target": target,
        "label": label,
        "condition": None,
    }


def _make_valid_workflow_doc():
    """Create a minimal valid workflow document."""
    return _make_workflow_doc(
        nodes=[_make_start_node(), _make_agent_node(), _make_end_node()],
        edges=[
            _make_edge("edge1", "node_start", "node_agent"),
            _make_edge("edge2", "node_agent", "node_end"),
        ],
    )


# ── _validate_for_publish tests ──


class TestValidateForPublish:
    """Test WorkflowService._validate_for_publish static method."""

    def test_valid_workflow_passes(self):
        """A valid workflow should not raise."""
        doc = _make_valid_workflow_doc()
        # Should not raise
        WorkflowService._validate_for_publish(doc)

    def test_missing_start_node(self):
        """Workflow without start node should fail."""
        doc = _make_workflow_doc(
            nodes=[_make_end_node()],
            edges=[],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        assert exc_info.value.code == "WORKFLOW_VALIDATION_ERROR"
        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "NO_START_NODE" in error_codes

    def test_missing_end_node(self):
        """Workflow without end node should NOT fail (end node is optional)."""
        doc = _make_workflow_doc(
            nodes=[_make_start_node()],
            edges=[],
        )
        # Should not raise ValidationError
        WorkflowService._validate_for_publish(doc)

    def test_empty_nodes(self):
        """Workflow with no nodes should fail."""
        doc = _make_workflow_doc(nodes=[], edges=[])
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "NO_START_OR_END" in error_codes

    def test_no_edges(self):
        """Workflow with nodes but no edges should fail."""
        doc = _make_workflow_doc(
            nodes=[_make_start_node(), _make_end_node()],
            edges=[],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "NO_EDGES" in error_codes

    def test_edge_references_nonexistent_source(self):
        """Edge with non-existent source should fail."""
        doc = _make_workflow_doc(
            nodes=[_make_start_node(), _make_end_node()],
            edges=[_make_edge("edge1", "nonexistent_node", "node_end")],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "MISSING_NODE_IN_EDGE" in error_codes

    def test_edge_references_nonexistent_target(self):
        """Edge with non-existent target should fail."""
        doc = _make_workflow_doc(
            nodes=[_make_start_node(), _make_end_node()],
            edges=[_make_edge("edge1", "node_start", "nonexistent_node")],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "MISSING_NODE_IN_EDGE" in error_codes

    def test_agent_missing_agent_id(self):
        """Agent node without agent_id should fail."""
        agent = _make_agent_node(agent_id="")
        doc = _make_workflow_doc(
            nodes=[_make_start_node(), agent, _make_end_node()],
            edges=[
                _make_edge("edge1", "node_start", "node_agent"),
                _make_edge("edge2", "node_agent", "node_end"),
            ],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "AGENT_MISSING_ID" in error_codes

    def test_agent_missing_input_query(self):
        """Agent node without input_query should fail."""
        agent = _make_agent_node(input_query="")
        doc = _make_workflow_doc(
            nodes=[_make_start_node(), agent, _make_end_node()],
            edges=[
                _make_edge("edge1", "node_start", "node_agent"),
                _make_edge("edge2", "node_agent", "node_end"),
            ],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "AGENT_MISSING_QUERY" in error_codes
        # 消息应只提"查询"，不暴露内部变量名 user_query
        assert "查询" in exc_info.value.details["errors"][0]["message"]

    def test_tool_missing_tool_id(self):
        """Tool node without tool_id should fail."""
        tool = _make_tool_node(tool_id="")
        doc = _make_workflow_doc(
            nodes=[_make_start_node(), tool, _make_end_node()],
            edges=[
                _make_edge("edge1", "node_start", "node_tool"),
                _make_edge("edge2", "node_tool", "node_end"),
            ],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "TOOL_MISSING_ID" in error_codes

    def test_gateway_no_conditions(self):
        """Gateway node without conditions should fail."""
        gateway = _make_gateway_node(empty=True)
        doc = _make_workflow_doc(
            nodes=[_make_start_node(), gateway, _make_end_node()],
            edges=[
                _make_edge("edge1", "node_start", "node_gateway"),
                _make_edge("edge2", "node_gateway", "node_end"),
            ],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "GATEWAY_NO_CONDITIONS" in error_codes

    def test_human_missing_title(self):
        """Human node without title should fail."""
        human = _make_human_node(title="")
        doc = _make_workflow_doc(
            nodes=[_make_start_node(), human, _make_end_node()],
            edges=[
                _make_edge("edge1", "node_start", "node_human"),
                _make_edge("edge2", "node_human", "node_end"),
            ],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        error_codes = [e["code"] for e in exc_info.value.details["errors"]]
        assert "HUMAN_MISSING_TITLE" in error_codes

    def test_multiple_errors_reported(self):
        """Multiple validation issues should all be reported."""
        doc = _make_workflow_doc(
            nodes=[
                _make_start_node(),
                _make_agent_node(agent_id=""),  # missing agent_id
                _make_tool_node(tool_id=""),    # missing tool_id
                _make_end_node(),
            ],
            edges=[
                _make_edge("edge1", "node_start", "node_agent"),
                _make_edge("edge2", "node_agent", "node_tool"),
                _make_edge("edge3", "node_tool", "node_end"),
            ],
        )
        with pytest.raises(ValidationError) as exc_info:
            WorkflowService._validate_for_publish(doc)

        errors = exc_info.value.details["errors"]
        error_codes = [e["code"] for e in errors]
        assert "AGENT_MISSING_ID" in error_codes
        assert "TOOL_MISSING_ID" in error_codes
        assert len(errors) == 2


# ── publish() integration tests ──


@pytest.mark.asyncio
class TestPublishWithValidation:
    """Test that publish() calls validation before changing status."""

    async def test_publish_valid_workflow(self, mock_database):
        """Publish a valid workflow should succeed."""
        doc = _make_valid_workflow_doc()

        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=doc)
        mock_col.find_one_and_update = AsyncMock(return_value={
            **doc,
            "status": "published",
            "version": 2,
        })
        mock_database.__getitem__.return_value = mock_col

        # Mock workflow registry service (imported lazily inside publish())
        with patch("app.services.workflow_registry_service.WorkflowRegistryService") as mock_registry:
            mock_registry.register = AsyncMock(return_value={"_id": "reg_new"})
            result = await WorkflowService.publish("wf_test123")

        assert result["status"] == "published"

    async def test_publish_invalid_workflow_raises(self, mock_database):
        """Publish an invalid workflow should raise ValidationError."""
        # Workflow missing start node
        doc = _make_workflow_doc(
            nodes=[_make_end_node()],
            edges=[],
        )

        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=doc)
        mock_database.__getitem__.return_value = mock_col

        with pytest.raises(ValidationError) as exc_info:
            await WorkflowService.publish("wf_test123")

        assert exc_info.value.code == "WORKFLOW_VALIDATION_ERROR"

    async def test_publish_already_published_raises_conflict(self, mock_database):
        """Publish an already published workflow should raise ConflictError."""
        doc = _make_valid_workflow_doc()
        doc["status"] = "published"

        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=doc)
        mock_database.__getitem__.return_value = mock_col

        with pytest.raises(ConflictError):
            await WorkflowService.publish("wf_test123")

    async def test_publish_not_found(self, mock_database):
        """Publish a non-existent workflow should raise NotFoundError."""
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)
        mock_database.__getitem__.return_value = mock_col

        with pytest.raises(NotFoundError):
            await WorkflowService.publish("wf_nonexistent")
