from unittest.mock import MagicMock, patch

from django.db import transaction

import pytest

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    DocumentProcessingRequestFactory,
    FigureExtractionResultFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterCategoryFactory,
    ParameterFactory,
    TextExtractionResultFactory,
)
from my_app.models import (
    FigureExtractionResult,
    L2ScreeningResult,
    ParameterExtractionResult,
    TextExtractionResult,
)
from my_app.services.document_post_processing import (
    enqueue_l2_screening_if_requested,
    enqueue_parameter_extraction_if_requested,
)

pytestmark = pytest.mark.backend


def _build_ready_citation():
    document = DocumentFactory()
    citation = CitationFactory(document=document)
    TextExtractionResultFactory(
        document=document,
        status=TextExtractionResult.TextExtractionStatus.COMPLETED,
    )
    FigureExtractionResultFactory(
        document=document,
        status=FigureExtractionResult.Status.COMPLETED,
    )
    l2_question = L2ScreeningQuestionFactory(review=citation.dataset.review)
    L2ScreeningQuestionOptionFactory(question=l2_question)
    parameter_category = ParameterCategoryFactory(
        review=citation.dataset.review
    )
    parameter = ParameterFactory(category=parameter_category)
    return citation, l2_question, parameter


def test_enqueue_l2_screening_runs_after_commit_when_requested(
    django_capture_on_commit_callbacks,
):
    citation, question, _parameter = _build_ready_citation()
    DocumentProcessingRequestFactory(
        citation=citation,
        should_run_l2_screening=True,
    )
    task_mock = MagicMock()

    with patch(
        "my_app.tasks.l2_screening.process_l2_screening_task", task_mock
    ):
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                enqueue_l2_screening_if_requested(citation.id)
                task_mock.enqueue.assert_not_called()

    result = L2ScreeningResult.objects.get(
        citation=citation,
        question=question,
    )
    task_mock.enqueue.assert_called_once_with(result_id=result.id)


def test_enqueue_parameter_extraction_runs_after_commit_when_requested(
    django_capture_on_commit_callbacks,
):
    citation, _question, parameter = _build_ready_citation()
    DocumentProcessingRequestFactory(
        citation=citation,
        should_run_parameter_extraction=True,
    )
    task_mock = MagicMock()

    with patch(
        "my_app.tasks.parameter_extraction.process_parameter_extraction_task",
        task_mock,
    ):
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                enqueue_parameter_extraction_if_requested(citation.id)
                task_mock.enqueue.assert_not_called()

    result = ParameterExtractionResult.objects.get(
        citation=citation,
        question=parameter,
    )
    task_mock.enqueue.assert_called_once_with(result_id=result.id)


@pytest.mark.parametrize(
    ("enqueue_function", "request_field", "service_path"),
    [
        (
            enqueue_l2_screening_if_requested,
            "should_run_l2_screening",
            "my_app.services.document_post_processing.DeferredL2ScreeningService",
        ),
        (
            enqueue_parameter_extraction_if_requested,
            "should_run_parameter_extraction",
            "my_app.services.document_post_processing.DeferredParameterExtractionService",
        ),
    ],
)
def test_post_processing_uses_flags_from_most_recent_request(
    django_capture_on_commit_callbacks,
    enqueue_function,
    request_field,
    service_path,
):
    citation, _question, _parameter = _build_ready_citation()
    DocumentProcessingRequestFactory(
        citation=citation,
        **{request_field: True},
    )
    DocumentProcessingRequestFactory(
        citation=citation,
        **{request_field: False},
    )

    with patch(service_path) as service:
        with django_capture_on_commit_callbacks(execute=True):
            enqueue_function(citation.id)

    service.assert_not_called()


@pytest.mark.parametrize(
    ("enqueue_function", "request_field", "result_model", "service_path"),
    [
        (
            enqueue_l2_screening_if_requested,
            "should_run_l2_screening",
            L2ScreeningResult,
            "my_app.services.document_post_processing.DeferredL2ScreeningService",
        ),
        (
            enqueue_parameter_extraction_if_requested,
            "should_run_parameter_extraction",
            ParameterExtractionResult,
            "my_app.services.document_post_processing.DeferredParameterExtractionService",
        ),
    ],
)
def test_post_processing_skips_when_a_result_is_newer_than_request(
    django_capture_on_commit_callbacks,
    enqueue_function,
    request_field,
    result_model,
    service_path,
):
    citation, question, parameter = _build_ready_citation()
    DocumentProcessingRequestFactory(
        citation=citation,
        **{request_field: True},
    )
    result_model.objects.create(
        citation=citation,
        question=(
            question if result_model is L2ScreeningResult else parameter
        ),
    )

    with patch(service_path) as service:
        with django_capture_on_commit_callbacks(execute=True):
            enqueue_function(citation.id)

    service.assert_not_called()


@pytest.mark.parametrize(
    ("enqueue_function", "request_field", "result_model", "service_path"),
    [
        (
            enqueue_l2_screening_if_requested,
            "should_run_l2_screening",
            L2ScreeningResult,
            "my_app.services.document_post_processing.DeferredL2ScreeningService",
        ),
        (
            enqueue_parameter_extraction_if_requested,
            "should_run_parameter_extraction",
            ParameterExtractionResult,
            "my_app.services.document_post_processing.DeferredParameterExtractionService",
        ),
    ],
)
def test_post_processing_requests_overwrite_for_results_older_than_request(
    django_capture_on_commit_callbacks,
    enqueue_function,
    request_field,
    result_model,
    service_path,
):
    citation, question, parameter = _build_ready_citation()
    result_model.objects.create(
        citation=citation,
        question=(
            question if result_model is L2ScreeningResult else parameter
        ),
    )
    DocumentProcessingRequestFactory(
        citation=citation,
        **{request_field: True},
    )

    with patch(service_path) as service:
        with django_capture_on_commit_callbacks(execute=True):
            enqueue_function(citation.id)

    service.assert_called_once()
    assert service.call_args.kwargs["overwrite_existing"] is True


@pytest.mark.parametrize(
    ("enqueue_function", "request_field", "service_path"),
    [
        (
            enqueue_l2_screening_if_requested,
            "should_run_l2_screening",
            "my_app.services.document_post_processing.DeferredL2ScreeningService",
        ),
        (
            enqueue_parameter_extraction_if_requested,
            "should_run_parameter_extraction",
            "my_app.services.document_post_processing.DeferredParameterExtractionService",
        ),
    ],
)
def test_post_processing_waits_for_both_extractions(
    django_capture_on_commit_callbacks,
    enqueue_function,
    request_field,
    service_path,
):
    citation, _question, _parameter = _build_ready_citation()
    citation.document.figure_extraction_result.status = (
        FigureExtractionResult.Status.PENDING
    )
    citation.document.figure_extraction_result.save()
    DocumentProcessingRequestFactory(
        citation=citation,
        **{request_field: True},
    )

    with patch(service_path) as service:
        with django_capture_on_commit_callbacks(execute=True):
            enqueue_function(citation.id)

    service.assert_not_called()
