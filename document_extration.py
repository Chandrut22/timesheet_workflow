
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    RapidOcrOptions,
)
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
    ImageFormatOption,
)


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



def create_converter() -> DocumentConverter:
    """Create a Docling converter for supported document formats."""

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
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options,
            ),
            InputFormat.IMAGE: ImageFormatOption(
                pipeline_options=pipeline_options,
            ),
            # XLSX and DOCX use Docling's default handlers.
        },
    )


# Create the converter once and reuse it.
converter = create_converter()


def extract_document(file_path: str | Path) -> str:
    """
    Extract text and tables from PDF, image, Excel, and Word files.

    Returns:
        Extracted document content in Markdown format.
    """

    path = Path(file_path)

    # Validate that the file exists.
    if not path.exists():
        raise FileNotFoundError(
            f"File not found: {path}"
        )

    if not path.is_file():
        raise ValueError(
            f"Path is not a file: {path}"
        )

    # Validate the file extension.
    extension = path.suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_EXTENSIONS))
        raise ValueError(
            f"Unsupported file type: {extension}. "
            f"Supported extensions: {supported}"
        )

    # Convert the document using Docling.
    result = converter.convert(path)

    # Export detected content as Markdown.
    markdown = result.document.export_to_markdown()

    if not markdown or not markdown.strip():
        raise RuntimeError(
            f"No text extracted from {path.name}. "
            "Check the document content, format, and OCR settings."
        )

    print(markdown)

    return markdown.strip()


def build_source_text(
    file_path: str | Path | None = None,
    email_body: str | None = None,
) -> str:
    """
    Combine extracted attachment content with the email body.

    At least one source must be provided.
    """

    parts: list[str] = []

    # Extract attachment content when provided.
    if file_path is not None:
        path = Path(file_path)
        document_text = extract_document(path)

        parts.append(
            f"ATTACHMENT: {path.name}\n"
            f"{document_text}"
        )

    # Include the email body when provided.
    if email_body and email_body.strip():
        parts.append(
            f"EMAIL BODY:\n{email_body.strip()}"
        )

    if not parts:
        raise ValueError(
            "Provide a file path, an email body, or both."
        )

    return "\n\n--- SOURCE SEPARATOR ---\n\n".join(parts)

