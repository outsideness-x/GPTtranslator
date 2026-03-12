"""PDF pipeline package."""

from .ingestion import IngestionError, IngestionResult, create_initial_manifest_payload, initialize_book_workspace
from .extractor import (
    ExtractedBlock,
    ExtractedFootnote,
    ExtractedImage,
    ExtractedPage,
    ExtractionResult,
    PdfExtractionError,
    extract_pdf_structure,
    save_extraction_artifacts,
)
from .document_graph import (
    DocumentGraph,
    DocumentGraphError,
    build_document_graph,
    save_document_graph_artifacts,
    validate_document_graph,
)
from .inspector import InspectionReport, PageInspection, PdfInspectionError, inspect_pdf, save_inspection_report

__all__ = [
    "DocumentGraph",
    "DocumentGraphError",
    "ExtractedBlock",
    "ExtractedFootnote",
    "ExtractedImage",
    "ExtractedPage",
    "ExtractionResult",
    "IngestionError",
    "IngestionResult",
    "InspectionReport",
    "PageInspection",
    "PdfExtractionError",
    "PdfInspectionError",
    "build_document_graph",
    "create_initial_manifest_payload",
    "extract_pdf_structure",
    "inspect_pdf",
    "initialize_book_workspace",
    "save_document_graph_artifacts",
    "save_extraction_artifacts",
    "save_inspection_report",
    "validate_document_graph",
]
