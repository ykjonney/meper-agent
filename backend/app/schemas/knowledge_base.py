"""KnowledgeBase-related Pydantic schemas for API request/response."""
from __future__ import annotations

from pydantic import BaseModel, Field


class KbFileResponse(BaseModel):
    """A single .md file in a KB directory."""

    path: str
    content: str
    size: int = 0


class KbFileUpdate(BaseModel):
    """Request body for updating a single KB file's content."""

    content: str = Field(..., min_length=1, description="新的文件内容")


class KbFileTreeNode(BaseModel):
    """A node in the KB file tree (file or directory)."""

    key: str = Field(..., description="唯一标识（相对路径）")
    title: str = Field(..., description="显示名称")
    is_leaf: bool = Field(default=True)
    children: list[KbFileTreeNode] | None = Field(default=None)
    size: int = Field(default=0, description="文件大小（仅文件节点有效）")


class KbFileTreeResponse(BaseModel):
    """Response for KB file tree endpoint."""

    kb_id: str
    files: list[KbFileTreeNode]


class KnowledgeBaseResponse(BaseModel):
    """KnowledgeBase data returned in API responses."""

    id: str
    name: str
    description: str = ""
    type: str = "tree"
    embedding_model_id: str = ""
    # ── Wiki (THE tree-KB behaviour) ────────────────────────────────
    builder_model_id: str = ""
    last_build_status: str = ""
    last_build_at: str = ""
    last_build_error: str = ""
    owner_user_id: str = ""
    status: str = "active"
    file_count: int = 0
    total_size: int = 0
    created_at: str
    updated_at: str


class KnowledgeBaseListResponse(BaseModel):
    """Paginated knowledge base list response."""

    items: list[KnowledgeBaseResponse]
    total: int
    page: int
    page_size: int


class KnowledgeBaseCreate(BaseModel):
    """Schema for creating a new KnowledgeBase (POST)."""

    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    type: str = Field(
        default="tree",
        description="tree (Markdown 文件树，agent 探索) / vector (RAG 语义检索)",
    )
    builder_model_id: str = Field(
        default="",
        description="tree（Wiki）型的构建模型（Model 表 _id，用于一键构建）",
    )


class KnowledgeBaseUpdate(BaseModel):
    """Schema for updating an existing KnowledgeBase (PUT)."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    builder_model_id: str | None = Field(
        default=None, description="Wiki 构建模型（Model 表 _id）"
    )


class KbUploadErrorItem(BaseModel):
    """Single file error in an upload batch."""

    filename: str
    error: str


class KbUploadResponse(BaseModel):
    """Batch upload response — per-file results.

    KB files are not separate DB entities (they live on the FS), so
    ``created`` is a list of relative paths written, not full objects.
    For vector KBs, ``document_ids`` lists the created KnowledgeDocument ids.
    """

    created: list[str] = Field(default_factory=list, description="成功写入的相对路径/文件名")
    errors: list[KbUploadErrorItem] = Field(default_factory=list)
    document_ids: list[str] = Field(
        default_factory=list, description="vector KB: 创建的文档 id 列表"
    )


# ── Vector KB: documents + retrieval ────────────────────────────────────


class KbDocumentItem(BaseModel):
    """A document in a vector KB (KnowledgeDocument metadata)."""

    id: str
    name: str
    file_type: str
    file_size: int = 0
    parse_status: str = "pending"
    parse_progress: int = 0
    parse_error: str = ""
    chunk_count: int = 0
    chunk_strategy: str = "recursive"
    created_at: str
    updated_at: str


class KbDocumentListResponse(BaseModel):
    """Paginated document list for a vector KB."""

    items: list[KbDocumentItem]
    total: int
    page: int
    page_size: int


class KbSearchRequest(BaseModel):
    """Body for the vector KB retrieval-test endpoint."""

    query: str = Field(..., min_length=1, description="检索查询文本")
    top_k: int = Field(default=5, ge=1, le=50, description="返回结果数")


class KbSearchResultItem(BaseModel):
    """One retrieved chunk with citation metadata."""

    text: str
    score: float
    doc_id: str = ""
    source_file: str = ""
    page: int | None = None
    section: str = ""
    image_ref_ids: list[str] = Field(default_factory=list)


class KbSearchResponse(BaseModel):
    """Retrieval-test response."""

    query: str
    results: list[KbSearchResultItem]


class KbChunkItem(BaseModel):
    """One parsed chunk of a document (read-only viewer)."""

    chunk_index: int
    text: str
    source_file: str = ""
    page: int | None = None
    section: str = ""
    image_ref_ids: list[str] = Field(default_factory=list)


# ── Wiki mode (llmwiki-style compiled wiki on tree KBs) ─────────────────


class KbWikiSourceItem(BaseModel):
    """One source file in a wiki-mode KB (with extraction status)."""

    path: str
    name: str
    size: int = 0
    file_type: str = ""
    status: str = Field(
        "ready", description="pending / processing / ready / failed（md 恒为 ready）"
    )
    error: str = ""
    has_registry: bool = Field(True, description="是否在登记表中（False=手动放入）")


class KbWikiFilesResponse(BaseModel):
    """Wiki-mode file view: page tree + source list."""

    kb_id: str
    wiki: list[KbFileTreeNode] = Field(default_factory=list)
    sources: list[KbWikiSourceItem] = Field(default_factory=list)


class KbWikiLintIssue(BaseModel):
    """One lint finding."""

    severity: str = Field(..., description="error / warn / info")
    rule: str
    path: str
    detail: str


class KbWikiLintStats(BaseModel):
    page_count: int = 0
    source_count: int = 0
    cited_source_count: int = 0
    error_count: int = 0
    warn_count: int = 0


class KbWikiLintResponse(BaseModel):
    issues: list[KbWikiLintIssue] = Field(default_factory=list)
    stats: KbWikiLintStats = Field(default_factory=KbWikiLintStats)

