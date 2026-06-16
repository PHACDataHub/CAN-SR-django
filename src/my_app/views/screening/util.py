from typing import Any, Dict

from my_app.models import (
    ScreeningResultStatus,
    TextExtractionResult,
)
from shortcuts import get_request, reverse, tdt

SCREENING_STATUS_BADGE_CLASSES = {
    ScreeningResultStatus.NOT_STARTED: "bg-secondary",
    ScreeningResultStatus.PENDING: "bg-warning text-dark",
    ScreeningResultStatus.COMPLETED: "bg-success",
    ScreeningResultStatus.ABANDONED: "bg-danger",
}

DOCUMENT_UPLOAD_BADGE_CLASSES = {
    "uploaded": "bg-success",
    "missing": "bg-secondary",
}

TEXT_EXTRACTION_BADGE_CLASSES = {
    TextExtractionResult.TextExtractionStatus.NOT_STARTED: "bg-secondary",
    TextExtractionResult.TextExtractionStatus.PENDING: "bg-warning text-dark",
    TextExtractionResult.TextExtractionStatus.COMPLETED: "bg-success",
    TextExtractionResult.TextExtractionStatus.FAILED: "bg-danger",
}

BADGE_CLASSES: Dict[Any, str] = {
    **SCREENING_STATUS_BADGE_CLASSES,
    **DOCUMENT_UPLOAD_BADGE_CLASSES,
    **TEXT_EXTRACTION_BADGE_CLASSES,
}


def can_start_l2_screening(citation_row):
    document = citation_row.document
    if document is None:
        return False

    text_extraction_result = getattr(document, "text_extraction_result", None)
    if text_extraction_result is None:
        return False

    return (
        text_extraction_result.status
        == TextExtractionResult.TextExtractionStatus.COMPLETED
    )


def get_page_number() -> int:
    request = get_request()

    try:
        page_number = int(request.GET.get("page", 1))
    except (TypeError, ValueError):
        page_number = 1

    return page_number
