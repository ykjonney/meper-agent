"""KbWikiDocument data model — source-file extraction registry for wiki KBs.

Wiki mode (tree KB upgrade, llmwiki-style) keeps the filesystem as the
source of truth (``sources/`` originals + ``sources/.extracted/`` text).
This collection registers **source files only** and tracks the async
extraction lifecycle so the UI can show real pending/ready/failed status
(wiki pages are plain ``.md`` and need no registry — stats/lint scan the
FS directly).

Lifecycle: ``pending → processing → ready | failed``. Everything here is
derived state: the registry can be rebuilt by re-uploading sources (or
re-running extraction); deleting it never loses knowledge.
"""
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from app.models.base import generate_id, utc_now

# Extraction lifecycle states.
PENDING = "pending"
PROCESSING = "processing"
READY = "ready"
FAILED = "failed"

# Only these extensions go through the async extraction pipeline; .md
# sources are readable as-is and are registered directly as ready.
EXTRACTABLE_TYPES = {"pdf", "docx", "pptx", "xlsx", "csv", "txt", "html", "htm"}


class KbWikiDocument(BaseModel):
    """MongoDB kb_wiki_documents document model (wiki-mode tree KB only)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("kbwsrc"), alias="_id")
    knowledge_base_id: str = Field(..., description="所属 wiki 知识库 _id")
    # Original file, relative to the KB root, always under ``sources/``.
    relative_path: str = Field(..., description="sources/ 下的原始文件相对路径")
    file_type: str = Field(default="", description="pdf / docx / md / txt …")
    file_size: int = Field(default=0, ge=0)
    # Extraction lifecycle: pending → processing → ready | failed
    status: str = Field(default=PENDING)
    error: str = Field(default="", description="失败原因（status=failed 时填充）")
    # sha256 of the original bytes — skip re-extraction on re-upload.
    content_hash: str = Field(default="")
    # sha256 of the content at the LAST successful wiki build that covered
    # this source (stamped by the build task). content_hash != digest_hash
    # while a cited (already-digested) source was re-uploaded with new
    # content → it re-enters the builder's pending list.
    digest_hash: str = Field(default="")
    # Extracted text path (relative to KB root) for binary sources, e.g.
    # ``sources/.extracted/report.md``. Empty for .md sources (read directly).
    extracted_path: str = Field(default="")
    extracted_at: str = Field(default="", description="提取完成时间")
    uploaded_by: str = Field(default="", description="上传者 user_id")
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())


__all__ = [
    "KbWikiDocument",
    "PENDING",
    "PROCESSING",
    "READY",
    "FAILED",
    "EXTRACTABLE_TYPES",
]
