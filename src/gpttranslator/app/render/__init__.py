"""Rendering pipeline package."""

from .assets import AssetBundle, AssetCollectionError, AssetCopyRecord, collect_image_assets
from .composer import (
    BuildComposition,
    ComposedPage,
    ComposedTextBlock,
    ComposerError,
    compose_document,
)
from .pdf_writer import PdfBuildResult, PdfWriteError, write_translated_pdf
from .service import BuildOptions, BuildResult, build_translated_book
from .typesetter import (
    AnnotationSpec,
    FallbackMode,
    FootnoteAreaPolicy,
    PageMargins,
    ReflowPageSpec,
    TypesetDocument,
    TypesetMetrics,
    TypesetterError,
    TypesettingConfig,
    build_typesetting_config,
    typeset_composition,
)

__all__ = [
    "AssetBundle",
    "AssetCollectionError",
    "AssetCopyRecord",
    "collect_image_assets",
    "BuildComposition",
    "ComposerError",
    "ComposedPage",
    "ComposedTextBlock",
    "compose_document",
    "PdfBuildResult",
    "PdfWriteError",
    "write_translated_pdf",
    "BuildOptions",
    "BuildResult",
    "build_translated_book",
    "AnnotationSpec",
    "FallbackMode",
    "FootnoteAreaPolicy",
    "PageMargins",
    "ReflowPageSpec",
    "TypesetDocument",
    "TypesetMetrics",
    "TypesettingConfig",
    "TypesetterError",
    "build_typesetting_config",
    "typeset_composition",
]
