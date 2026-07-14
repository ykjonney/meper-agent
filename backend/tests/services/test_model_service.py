"""Tests for Model schema validation (base_url) & search regex injection (问题 1 & 6)."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError


class _Cursor:
    """Minimal mock of a Motor cursor for list_models."""

    def __init__(self, items):
        self._items = items

    def sort(self, *a, **kw):
        return self

    def skip(self, n):
        return self

    def limit(self, n):
        return self

    async def to_list(self, length):
        return self._items[:length]


# ---------------------------------------------------------------------------
# 问题 6：base_url 格式校验
# ---------------------------------------------------------------------------


class TestBaseUrlValidation:
    """ModelCreate / ModelUpdate 的 base_url 必须是合法 http(s) URL。"""

    _valid = {
        "model_id": "deepseek-chat",
        "name": "DS",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "sk-x",
    }

    @pytest.mark.parametrize(
        "bad_url",
        [
            "   ",
            "乱码",
            "javascript:alert(1)",
            "file:///etc/passwd",
            "ftp://x.com",
            "http://",  # 缺 netloc
            "not a url",
            "://no-scheme",
        ],
    )
    def test_invalid_base_url_rejected(self, bad_url) -> None:
        from app.schemas.model import ModelCreate, ModelUpdate

        for schema in (ModelCreate, ModelUpdate):
            with pytest.raises(ValidationError):
                schema(**{**self._valid, "base_url": bad_url})

    @pytest.mark.parametrize(
        "good_url",
        [
            "https://api.deepseek.com/v1",
            "http://localhost:11434",
            "https://api.openai.com/v1/",
        ],
    )
    def test_valid_base_url_accepted(self, good_url) -> None:
        from app.schemas.model import ModelCreate

        m = ModelCreate(**{**self._valid, "base_url": good_url})
        assert m.base_url == good_url.strip()


# ---------------------------------------------------------------------------
# 问题 1：list_models 搜索的 regex 注入防护
# ---------------------------------------------------------------------------


class TestListModelsRegexEscape:
    """provider_tag 搜索必须转义 regex 特殊字符，防止 ``.*`` 返回全部。"""

    @pytest.mark.asyncio
    async def test_provider_tag_regex_escaped(self) -> None:
        from app.services.model_service import ModelService

        col = MagicMock()
        col.count_documents = AsyncMock(return_value=0)
        col.find.return_value = _Cursor([])

        with patch(
            "app.services.model_service.ModelService._collection",
            return_value=col,
        ):
            await ModelService.list_models(page=1, page_size=20, provider_tag=".*")

        filter_query = col.count_documents.call_args[0][0]
        assert filter_query["provider_tag"]["$regex"] == r"\.\*"
        assert filter_query["provider_tag"]["$options"] == "i"
