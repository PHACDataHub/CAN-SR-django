from proj.util import MissingPreconditionError

from my_app.models import (
    Citation,
    FigureExtractionResult,
    TextExtractionResult,
)


def get_text_extraction_result_for_citation(
    citation: Citation,
) -> TextExtractionResult:
    document = citation.document
    if document is None:
        raise MissingPreconditionError(
            f"This operation requires a document to be attached to the citation."
        )

    try:
        text_extraction_result = document.text_extraction_result
    except TextExtractionResult.DoesNotExist as exc:
        raise MissingPreconditionError(
            f"This operation requires text extraction to be completed for the attached document."
        ) from exc

    if (
        text_extraction_result.status
        != TextExtractionResult.TextExtractionStatus.COMPLETED
    ):
        raise MissingPreconditionError(
            f"This operation requires text extraction to be completed for the attached document."
        )

    return text_extraction_result


def get_figure_extraction_result_for_citation(
    citation: Citation,
) -> FigureExtractionResult:
    document = citation.document
    if document is None:
        raise MissingPreconditionError(
            f"This operation requires a document to be attached to the citation."
        )

    try:
        figure_extraction_result = document.figure_extraction_result
    except FigureExtractionResult.DoesNotExist as exc:
        raise MissingPreconditionError(
            f"This operation requires figure extraction to be completed for the attached document."
        ) from exc

    if (
        figure_extraction_result.status
        != FigureExtractionResult.Status.COMPLETED
    ):
        raise MissingPreconditionError(
            f"This operation requires figure extraction to be completed for the attached document."
        )

    return figure_extraction_result
