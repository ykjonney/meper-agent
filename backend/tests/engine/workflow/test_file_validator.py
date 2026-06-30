"""file_validator unit tests — FileRef validation for workflow start node.

所有外部依赖（FileService.get / load_content）均 mock，不依赖真实数据库。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.engine.workflow.file_validator import (
    FileVariableValue,
    validate_file_variable,
)
from app.models.file_library import FileConsumerKind, FileRef


def _make_file_ref(
    *,
    file_id: str = "file_TEST",
    name: str = "report.pdf",
    size: int = 1024,
    mime_type: str = "application/pdf",
) -> FileRef:
    return FileRef(
        id=file_id,
        owner_user_id="user_TEST",
        storage_key=f"user_TEST/files/{file_id}",
        name=name,
        size=size,
        mime_type=mime_type,
        sha256="abc123",
        origin_kind=FileConsumerKind.USER_LIBRARY,
        origin_id="user_TEST",
    )


class TestValidateFileVariable:
    """validate_file_variable 独立验证器测试。"""

    # ------------------------------------------------------------------
    # 正常路径
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_single_file_ok(self) -> None:
        """单文件正常解析。"""
        fref = _make_file_ref()
        mock_get = AsyncMock(return_value=fref)
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_TEST", {})
        assert error is None
        assert resolved is not None
        # 单文件返回 dict
        assert resolved["file_id"] == "file_TEST"
        assert resolved["name"] == "report.pdf"
        assert resolved["size"] == 1024
        assert resolved["mime_type"] == "application/pdf"
        assert resolved["storage_key"] == "user_TEST/files/file_TEST"

    @pytest.mark.asyncio
    async def test_multiple_files_ok(self) -> None:
        """多文件（multiple=True）正常解析为列表。"""
        fref1 = _make_file_ref(file_id="f1", name="a.pdf")
        fref2 = _make_file_ref(file_id="f2", name="b.txt", mime_type="text/plain")
        mock_get = AsyncMock(side_effect=[fref1, fref2])
        var_def = {"constraints": {"multiple": True}}
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable(["f1", "f2"], var_def)
        assert error is None
        assert isinstance(resolved, list)
        assert len(resolved) == 2
        assert resolved[0]["file_id"] == "f1"
        assert resolved[1]["name"] == "b.txt"

    @pytest.mark.asyncio
    async def test_single_file_list_with_multiple_false(self) -> None:
        """multiple=False 但传入单元素 list → 返回 dict（非 list）。"""
        fref = _make_file_ref()
        mock_get = AsyncMock(return_value=fref)
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable(["file_TEST"], {})
        assert error is None
        # 单文件即使传入 list，multiple=False 时返回 dict
        assert isinstance(resolved, dict)
        assert resolved["file_id"] == "file_TEST"

    # ------------------------------------------------------------------
    # 错误路径
    # ------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_file_not_found(self) -> None:
        """FileRef 不存在 → 验证错误。"""
        mock_get = AsyncMock(return_value=None)
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_MISSING", {})
        assert resolved is None
        assert error is not None
        assert "不存在" in error

    @pytest.mark.asyncio
    async def test_wrong_extension(self) -> None:
        """扩展名不匹配 → 验证错误。"""
        fref = _make_file_ref(name="report.txt")
        mock_get = AsyncMock(return_value=fref)
        var_def = {"constraints": {"allowed_extensions": [".pdf", ".docx"]}}
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_TEST", var_def)
        assert resolved is None
        assert "扩展名" in error
        assert ".txt" in error

    @pytest.mark.asyncio
    async def test_extension_ok(self) -> None:
        """扩展名匹配 → 通过。"""
        fref = _make_file_ref(name="report.PDF")  # 大写扩展名
        mock_get = AsyncMock(return_value=fref)
        var_def = {"constraints": {"allowed_extensions": [".pdf"]}}
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_TEST", var_def)
        assert error is None
        assert resolved is not None

    @pytest.mark.asyncio
    async def test_file_too_large(self) -> None:
        """文件超限 → 验证错误。"""
        fref = _make_file_ref(size=10 * 1024 * 1024)  # 10 MB
        mock_get = AsyncMock(return_value=fref)
        var_def = {"constraints": {"max_size_mb": 5}}
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_TEST", var_def)
        assert resolved is None
        assert "超过限制" in error
        assert "5" in error  # max_size_mb 值

    @pytest.mark.asyncio
    async def test_file_size_ok(self) -> None:
        """文件未超限 → 通过。"""
        fref = _make_file_ref(size=3 * 1024 * 1024)  # 3 MB
        mock_get = AsyncMock(return_value=fref)
        var_def = {"constraints": {"max_size_mb": 5}}
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_TEST", var_def)
        assert error is None
        assert resolved is not None

    @pytest.mark.asyncio
    async def test_multiple_not_allowed(self) -> None:
        """multiple=False 但传入多个 ID → 错误。"""
        var_def = {"constraints": {"multiple": False}}
        resolved, error = await validate_file_variable(["f1", "f2"], var_def)
        assert resolved is None
        assert "多文件" in error

    @pytest.mark.asyncio
    async def test_invalid_value_type(self) -> None:
        """value 类型错误（非 str/list）→ 错误。"""
        resolved, error = await validate_file_variable(12345, {})  # type: ignore[arg-type]
        assert resolved is None
        assert "类型" in error or "ID" in error

    @pytest.mark.asyncio
    async def test_multiple_partial_invalid(self) -> None:
        """多文件中部分无效 → 明确报错位置。"""
        fref1 = _make_file_ref(file_id="f1", name="a.pdf")
        mock_get = AsyncMock(side_effect=[fref1, None])  # f1 OK, f2 missing
        var_def = {"constraints": {"multiple": True}}
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable(["f1", "f2_missing"], var_def)
        assert resolved is None
        assert "f2_missing" in error  # 明确报错哪个文件 ID

    @pytest.mark.asyncio
    async def test_no_extension_file_with_extension_constraint(self) -> None:
        """文件无扩展名但约束要求扩展名 → 错误。"""
        fref = _make_file_ref(name="noextfile")
        mock_get = AsyncMock(return_value=fref)
        var_def = {"constraints": {"allowed_extensions": [".pdf"]}}
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_TEST", var_def)
        assert resolved is None
        assert "扩展名" in error

    @pytest.mark.asyncio
    async def test_empty_allowed_extensions_list(self) -> None:
        """allowed_extensions 为空列表 → 不做扩展名检查，全部通过。"""
        fref = _make_file_ref(name="anything.xyz")
        mock_get = AsyncMock(return_value=fref)
        var_def = {"constraints": {"allowed_extensions": []}}
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_TEST", var_def)
        assert error is None
        assert resolved is not None


# ── FileVariableValue.__str__ 渲染测试 ──────────────────────────


class TestFileVariableValueStr:
    """FileVariableValue 的 __str__ 输出格式验证。"""

    def test_text_file_str(self) -> None:
        """文本文件：输出 <file> XML 包含内容。"""
        fvv = FileVariableValue(
            file_id="f1", name="hello.txt", size=5,
            mime_type="text/plain", content="hello", truncated=False,
        )
        out = str(fvv)
        assert '<file id="f1"' in out
        assert 'name="hello.txt"' in out
        assert "hello" in out
        assert "</file>" in out

    def test_binary_file_str(self) -> None:
        """二进制文件：无 content，显示原因。"""
        fvv = FileVariableValue(
            file_id="f2", name="image.png", size=1024,
            mime_type="image/png", content_unavailable_reason="binary file",
        )
        out = str(fvv)
        assert "<file" in out
        assert "[binary file]" in out

    def test_truncated_file_str(self) -> None:
        """截断文件：内容后附截断提示。"""
        fvv = FileVariableValue(
            file_id="f3", name="big.log", size=999999,
            mime_type="text/plain", content="prefix_content", truncated=True,
        )
        out = str(fvv)
        assert "prefix_content" in out
        assert "truncated" in out

    def test_str_is_html_escaped(self) -> None:
        """文件名含特殊字符时应被 HTML 转义。"""
        fvv = FileVariableValue(
            file_id="f4", name='<script>alert("x")</script>',
            size=1, mime_type="text/plain", content="ok",
        )
        out = str(fvv)
        assert "<script>" not in out
        assert "&lt;script&gt;" in out


# ── validate_file_variable 内容加载测试 ────────────────────────


class TestValidateFileVariableWithContent:
    """验证 validate_file_variable 加载文件内容的行为。"""

    @pytest.mark.asyncio
    async def test_text_file_content_loaded(self) -> None:
        """文本文件：content 字段包含文件内容。"""
        fref = _make_file_ref(name="data.txt", mime_type="text/plain")
        mock_get = AsyncMock(return_value=fref)
        mock_load = AsyncMock(return_value=("data.txt", b"file content here"))
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            mock_svc.return_value.load_content = mock_load
            resolved, error = await validate_file_variable("file_TEST", {})
        assert error is None
        assert resolved is not None
        assert resolved["content"] == "file content here"
        assert resolved["truncated"] is False

    @pytest.mark.asyncio
    async def test_binary_file_no_content(self) -> None:
        """二进制文件：content 不存在，记录原因。"""
        fref = _make_file_ref(name="image.png", mime_type="image/png")
        mock_get = AsyncMock(return_value=fref)
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            resolved, error = await validate_file_variable("file_TEST", {})
        assert error is None
        assert resolved is not None
        assert "content" not in resolved or resolved.get("content") is None
        assert "binary" in resolved.get("content_unavailable_reason", "")

    @pytest.mark.asyncio
    async def test_content_truncated_when_too_long(self) -> None:
        """超长文本：截断并标记 truncated=True。"""
        from app.engine.workflow.file_validator import MAX_CONTENT_CHARS

        long_text = "A" * (MAX_CONTENT_CHARS + 1000)
        fref = _make_file_ref(name="big.log", mime_type="text/plain")
        mock_get = AsyncMock(return_value=fref)
        mock_load = AsyncMock(return_value=("big.log", long_text.encode("utf-8")))
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            mock_svc.return_value.load_content = mock_load
            resolved, error = await validate_file_variable("file_TEST", {})
        assert error is None
        assert resolved is not None
        assert resolved["truncated"] is True
        assert len(resolved["content"]) == MAX_CONTENT_CHARS

    @pytest.mark.asyncio
    async def test_content_load_failure(self) -> None:
        """文件加载失败：不报错，记录原因。"""
        fref = _make_file_ref(name="gone.txt", mime_type="text/plain")
        mock_get = AsyncMock(return_value=fref)
        mock_load = AsyncMock(side_effect=FileNotFoundError("missing"))
        with patch("app.engine.workflow.file_validator._get_file_service") as mock_svc:
            mock_svc.return_value.get = mock_get
            mock_svc.return_value.load_content = mock_load
            resolved, error = await validate_file_variable("file_TEST", {})
        assert error is None
        assert resolved is not None
        assert "load failed" in resolved.get("content_unavailable_reason", "")

    @pytest.mark.asyncio
    async def test_fvv_str_via_jinja_render(self) -> None:
        """验证 FileVariableValue 在 Jinja2 模板中 __str__ 正确输出。"""
        fvv = FileVariableValue(
            file_id="f1", name="test.py", size=42,
            mime_type="text/x-python", content="print('hi')", truncated=False,
        )
        from jinja2 import Template

        tpl = Template("变量内容: {{ data_file }}")
        rendered = tpl.render(data_file=fvv)
        assert '<file id="f1"' in rendered
        assert "print(" in rendered
        assert "</file>" in rendered
