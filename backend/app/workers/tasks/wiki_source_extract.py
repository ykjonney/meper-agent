"""Wiki-mode source extraction — async Celery task.

Pipeline per registered source:
    read original (sources/…) → parse (vector KB parser suite, PDF may
    use vision/OCR) → write paginated markdown to
    ``sources/.extracted/{name}.md`` → mark registry ready.

Extraction is text-only (no chunking/embedding — that's Phase 2). Page
markers ``<!-- p.N -->`` make the text page-addressable so wiki footnote
citations (``sources/x.pdf, p.3``) and ``kb_read(pages=…)`` line up.

Idempotent: re-running overwrites the extracted text in place.
"""
from typing import TYPE_CHECKING, Any

from loguru import logger

from app.workers.celery_app import celery_app
from app.workers.loop import run_async

if TYPE_CHECKING:
    from app.engine.kb.vector.parser.base import ParseResult


@celery_app.task(name="app.workers.tasks.wiki_source_extract.extract_wiki_source")
def extract_wiki_source(doc_id: str) -> dict[str, Any]:
    """Extract one registered wiki source to markdown (Celery entry)."""
    return run_async(_extract_async(doc_id))


async def _extract_async(doc_id: str) -> dict[str, Any]:
    from app.engine.kb.tree import fs as kb_fs
    from app.engine.kb.vector.parser import parse
    from app.services import kb_wiki_registry

    reg = await kb_wiki_registry.get(doc_id)
    if reg is None:
        logger.error("kb_wiki_extract_not_found", doc_id=doc_id)
        return {"status": "not_found", "doc_id": doc_id}

    kb_id = reg["knowledge_base_id"]
    rel_path = reg["relative_path"]
    try:
        await kb_wiki_registry.set_status(doc_id, kb_wiki_registry.processing_status())

        base = kb_fs.get_kb_base_path(kb_id)
        src = base / rel_path
        if not src.is_file():
            raise RuntimeError(f"源文件不存在: {rel_path}")
        raw = src.read_bytes()
        ft = (reg.get("file_type") or src.suffix.lstrip(".")).lower()

        if ft == "pdf":
            parse_result = await _parse_pdf(raw)
        else:
            parse_result = parse(raw, ft, structured=True)

        text = _blocks_to_markdown(parse_result, src.name)
        if not text.strip():
            raise RuntimeError("解析后无有效文本（可能为纯图片扫描件且未配置 OCR/vision）")

        extracted_rel = kb_fs.extracted_path_for(kb_id, rel_path)
        kb_fs.write_kb_file(kb_id, extracted_rel, text)
        await kb_wiki_registry.mark_extracted(doc_id)
        pages = parse_result.total_pages or _count_markers(text)
        logger.info(
            "kb_wiki_extract_completed",
            kb_id=kb_id,
            rel_path=rel_path,
            pages=pages,
            chars=len(text),
        )
        return {"status": "ready", "doc_id": doc_id, "pages": pages}

    except Exception as exc:
        logger.exception("kb_wiki_extract_failed", kb_id=kb_id, rel_path=rel_path)
        await kb_wiki_registry.mark_failed(doc_id, str(exc))
        return {"status": "failed", "doc_id": doc_id, "error": str(exc)}


async def _parse_pdf(raw: bytes) -> "ParseResult":
    """PDF parse with optional vision/OCR (mirrors kb_indexing's branch).

    Image FileRefs are created against the registry doc id — they're not
    consumed by Phase-1 wiki reads, but the OCR'd text lands in blocks.
    """
    from app.engine.kb.vector.factory import get_ocr_engine, get_vision_client
    from app.engine.kb.vector.parser import parse

    vision_client = get_vision_client()
    ocr_engine = get_ocr_engine()
    if vision_client is not None or ocr_engine is not None:
        from app.core.config import settings
        from app.engine.kb.vector.parser.image_extractor import ImageExtractor
        from app.engine.kb.vector.parser.pdf_parser import parse_pdf_with_images
        from app.services.file_service import FileService
        from app.services.file_storage import LocalFileStorage

        extractor = ImageExtractor(
            vision_client=vision_client,
            ocr_engine=ocr_engine,
            file_service=FileService(storage=LocalFileStorage()),
            doc_id="wiki-extract",
            owner_id="system",
            extract_images=settings.KB_EXTRACT_IMAGES,
        )
        return await parse_pdf_with_images(raw, extractor)
    return parse(raw, "pdf")


def _blocks_to_markdown(result: "ParseResult", filename: str) -> str:
    """Flatten TextBlocks into page-marked markdown.

    Page markers ``<!-- p.N -->`` precede each new page; ``section`` paths
    become ``## 标题`` lines so ``kb_read(sections=…)`` can slice them.
    """
    parts: list[str] = [f"<!-- source: {filename} -->"]
    last_page: int | None = None
    last_section = ""
    for block in result.blocks:
        text = block.text.strip()
        if not text:
            continue
        if block.page is not None and block.page != last_page:
            parts.append(f"<!-- p.{block.page} -->")
            last_page = block.page
            last_section = ""  # 新页重置节标题，避免重复打印
        if block.section and block.section != last_section:
            parts.append(f"## {block.section}")
            last_section = block.section
        parts.append(text)
    return "\n\n".join(parts) + "\n"


def _count_markers(text: str) -> int:
    import re

    return len(re.findall(r"(?m)^<!-- p\.(\d+) -->", text))


__all__ = ["extract_wiki_source"]
