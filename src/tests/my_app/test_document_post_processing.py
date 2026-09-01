from unittest.mock import patch

import pytest

from proj.models import TaskGroup

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterCategoryFactory,
    ParameterFactory,
)
from my_app.models import L2ScreeningResult, ParameterExtractionResult
from my_app.services.document_post_processing import (
    RequestedDocumentPostProcessingService,
)

pytestmark = pytest.mark.backend


def _build_citation_and_group():
    document = DocumentFactory()
    citation = CitationFactory(document=document)
    question = L2ScreeningQuestionFactory(review=citation.dataset.review)
    L2ScreeningQuestionOptionFactory(question=question)
    category = ParameterCategoryFactory(review=citation.dataset.review)
    parameter = ParameterFactory(category=category)
    group = TaskGroup.objects.create(key=f"process-document:{document.id}")
    return citation, question, parameter, group


def _service(group, citation, **kwargs):
    return RequestedDocumentPostProcessingService(
        task_group_id=group.id,
        citation_id=citation.id,
        should_run_l2_screening=kwargs.get("should_run_l2_screening", False),
        should_run_parameter_extraction=kwargs.get(
            "should_run_parameter_extraction", False
        ),
    )


def test_requested_post_processing_enqueues_selected_work():
    citation, question, parameter, group = _build_citation_and_group()

    with (
        patch(
            "my_app.services.document_post_processing.DeferredL2ScreeningService"
        ) as l2_service,
        patch(
            "my_app.services.document_post_processing.DeferredParameterExtractionService"
        ) as parameter_service,
    ):
        _service(
            group,
            citation,
            should_run_l2_screening=True,
            should_run_parameter_extraction=True,
        ).perform()

    assert l2_service.call_args.kwargs == {
        "rows": [citation],
        "questions": [question],
        "overwrite_existing": True,
    }
    l2_service.return_value.perform.assert_called_once_with()
    assert parameter_service.call_args.kwargs == {
        "rows": [citation],
        "questions": [parameter],
        "overwrite_existing": True,
    }
    parameter_service.return_value.perform.assert_called_once_with()


def test_requested_post_processing_ignores_a_superseded_group():
    citation, _question, _parameter, older_group = _build_citation_and_group()
    TaskGroup.objects.create(key=older_group.key)

    with patch(
        "my_app.services.document_post_processing.DeferredL2ScreeningService"
    ) as service:
        _service(
            older_group,
            citation,
            should_run_l2_screening=True,
        ).perform()

    service.assert_not_called()


@pytest.mark.parametrize(
    ("flag", "result_model", "service_path"),
    [
        (
            "should_run_l2_screening",
            L2ScreeningResult,
            "my_app.services.document_post_processing.DeferredL2ScreeningService",
        ),
        (
            "should_run_parameter_extraction",
            ParameterExtractionResult,
            "my_app.services.document_post_processing.DeferredParameterExtractionService",
        ),
    ],
)
def test_requested_post_processing_preserves_results_newer_than_group(
    flag,
    result_model,
    service_path,
):
    citation, question, parameter, group = _build_citation_and_group()
    result_model.objects.create(
        citation=citation,
        question=(
            question if result_model is L2ScreeningResult else parameter
        ),
    )

    with patch(service_path) as service:
        _service(group, citation, **{flag: True}).perform()

    service.assert_not_called()


@pytest.mark.parametrize(
    ("flag", "result_model", "service_path"),
    [
        (
            "should_run_l2_screening",
            L2ScreeningResult,
            "my_app.services.document_post_processing.DeferredL2ScreeningService",
        ),
        (
            "should_run_parameter_extraction",
            ParameterExtractionResult,
            "my_app.services.document_post_processing.DeferredParameterExtractionService",
        ),
    ],
)
def test_requested_post_processing_overwrites_results_older_than_group(
    flag,
    result_model,
    service_path,
):
    citation, question, parameter, _group = _build_citation_and_group()
    result_model.objects.create(
        citation=citation,
        question=(
            question if result_model is L2ScreeningResult else parameter
        ),
    )
    group = TaskGroup.objects.create(
        key=f"process-document:{citation.document_id}"
    )

    with patch(service_path) as service:
        _service(group, citation, **{flag: True}).perform()

    service.assert_called_once()
    assert service.call_args.kwargs["overwrite_existing"] is True
