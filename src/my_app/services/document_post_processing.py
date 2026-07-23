from django.db import transaction

from my_app.models import (
    Citation,
    DocumentProcessingRequest,
    L2ScreeningQuestion,
    L2ScreeningResult,
    Parameter,
    ParameterExtractionResult,
)
from my_app.queries import (
    is_ready_for_l2_screening,
    is_ready_for_parameter_extraction,
)
from my_app.services.l2_screening import DeferredL2ScreeningService
from my_app.services.parameter_extraction import (
    DeferredParameterExtractionService,
)


def _latest_processing_request(citation_id: int):
    return (
        DocumentProcessingRequest.objects.filter(citation_id=citation_id)
        .order_by("-requested_at", "-id")
        .first()
    )


def enqueue_l2_screening_if_requested(citation_id: int):
    def enqueue_if_ready():
        processing_request = _latest_processing_request(citation_id)
        if (
            processing_request is None
            or not processing_request.should_run_l2_screening
            or not is_ready_for_l2_screening(citation_id)
        ):
            return

        has_newer_results = L2ScreeningResult.objects.filter(
            citation_id=citation_id,
            created_at__gt=processing_request.requested_at,
        ).exists()
        if has_newer_results:
            return

        citation = Citation.objects.get(id=citation_id)
        questions = list(
            L2ScreeningQuestion.objects.filter(review=citation.dataset.review)
        )
        DeferredL2ScreeningService(
            rows=[citation],
            questions=questions,
            overwrite_existing=True,
        ).perform()

    transaction.on_commit(enqueue_if_ready)


def enqueue_parameter_extraction_if_requested(citation_id: int):
    def enqueue_if_ready():
        processing_request = _latest_processing_request(citation_id)
        if (
            processing_request is None
            or not processing_request.should_run_parameter_extraction
            or not is_ready_for_parameter_extraction(citation_id)
        ):
            return

        has_newer_results = ParameterExtractionResult.objects.filter(
            citation_id=citation_id,
            created_at__gt=processing_request.requested_at,
        ).exists()
        if has_newer_results:
            return

        citation = Citation.objects.get(id=citation_id)
        parameters = list(
            Parameter.objects.filter(category__review=citation.dataset.review)
        )
        DeferredParameterExtractionService(
            rows=[citation],
            questions=parameters,
            overwrite_existing=True,
        ).perform()

    transaction.on_commit(enqueue_if_ready)


def enqueue_requested_post_processing(document_id: int):
    citation_ids = Citation.objects.filter(
        document_id=document_id
    ).values_list("id", flat=True)
    for citation_id in citation_ids:
        enqueue_l2_screening_if_requested(citation_id)
        enqueue_parameter_extraction_if_requested(citation_id)
