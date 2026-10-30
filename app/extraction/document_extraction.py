"""Turn a timesheet document (PDF, image, Excel, Word) into Markdown text with Docling.

Works on a file path (CLI) or on raw bytes taken straight from an email (worker),
so attachments never need to be saved to disk.
"""
import logging
from functools import lru_cache
from io import BytesIO
from pathlib import Path

log = logging.getLogger("extraction.document")

# Supported attachment extensions
SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
    ".bmp",
    ".webp",
    ".xlsx",
    ".docx",
}

# Used when an attachment has no file extension
MIME_TO_EXTENSION = {
    "application/pdf": ".pdf",
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/tiff": ".tiff",
    "image/bmp": ".bmp",
    "image/webp": ".webp",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

SOURCE_SEPARATOR = "\n\n--- SOURCE SEPARATOR ---\n\n"


class NoTextError(RuntimeError):
    """The document opened, but no text could be read from it."""


@lru_cache(maxsize=1)
def get_converter():
    """Create the Docling converter once (it loads OCR models, so this is slow)."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
    from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption

    # Configure OCR for PDFs and images.
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = True
    pipeline_options.ocr_options = RapidOcrOptions(
        lang=["en"],
        force_full_page_ocr=True,
    )

    # Export embedded pictures when available.
    pipeline_options.generate_picture_images = True

    return DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.IMAGE,
            InputFormat.XLSX,
            InputFormat.DOCX,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pipeline_options),
            # XLSX and DOCX use Docling's default handlers.
        },
    )


def file_extension(file_name: str, mime_type: str | None = None) -> str:
    extension = Path(file_name).suffix.lower()
    if not extension and mime_type:
        extension = MIME_TO_EXTENSION.get(mime_type.lower(), "")
    return extension


def _check_extension(extension: str) -> None:
    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(f"Unsupported file type: {extension}. Supported extensions: {supported}")


def _to_markdown(source, display_name: str) -> str:
    result = get_converter().convert(source)
    markdown = result.document.export_to_markdown()

    if not markdown or not markdown.strip():
        raise NoTextError(
            f"No text extracted from {display_name}. "
            "Check the document content, format, and OCR settings."
        )

    log.debug("Extracted from %s:\n%s", display_name, markdown)
    return markdown.strip()


def extract_document(file_path: str | Path) -> str:
    """Extract text and tables from a file on disk. Returns Markdown."""
    path = Path(file_path)

    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Path is not a file: {path}")

    _check_extension(path.suffix.lower())
    return _to_markdown(path, path.name)


def extract_document_bytes(file_name: str, data: bytes) -> str:
    """Extract text and tables from file contents held in memory. Returns Markdown."""
    from docling.datamodel.base_models import DocumentStream

    _check_extension(Path(file_name).suffix.lower())
    if not data:
        raise NoTextError(f"{file_name} is empty.")
    return _to_markdown(DocumentStream(name=file_name, stream=BytesIO(data)), file_name)


def format_source_text(
    attachment_name: str | None = None,
    document_text: str | None = None,
    email_body: str | None = None,
) -> str:
    """Combine attachment content and the email body into one source for the LLM."""
    parts: list[str] = []

    if attachment_name and document_text:
        parts.append(f"ATTACHMENT: {attachment_name}\n{document_text}")

    if email_body and email_body.strip():
        parts.append(f"EMAIL BODY:\n{email_body.strip()}")

    if not parts:
        raise ValueError("Provide a file, an email body, or both.")

    return SOURCE_SEPARATOR.join(parts)


def build_source_text(
    file_path: str | Path | None = None,
    email_body: str | None = None,
) -> str:
    """CLI helper: extract a file on disk and combine it with an email body."""
    if file_path is None:
        return format_source_text(email_body=email_body)

    path = Path(file_path)
    return format_source_text(path.name, extract_document(path), email_body)
