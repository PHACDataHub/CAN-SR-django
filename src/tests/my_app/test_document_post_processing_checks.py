from unittest.mock import patch

import pytest

from proj.util import MissingPreconditionError

from my_app.model_factories import (
    CitationFactory,
    DocumentFactory,
    L2ScreeningQuestionFactory,
    L2ScreeningQuestionOptionFactory,
    ParameterCategoryFactory,
    ParameterFactory,
)
from my_app.models import DocumentProcessingRequest
from my_app.services.process_document import QueueProcessDocumentService

pytestmark = pytest.mark.backend


def test_queue_process_document_creates_request_and_queues_extractions():
    document = DocumentFactory()
    citation = CitationFactory(document=document)
    l2_question = L2ScreeningQuestionFactory(review=citation.dataset.review)
    L2ScreeningQuestionOptionFactory(question=l2_question)
    category = ParameterCategoryFactory(review=citation.dataset.review)
    ParameterFactory(category=category)

    with (
        patch(
            "my_app.services.process_document.QueueTextExtractionService"
        ) as text_service,
        patch(
            "my_app.services.process_document.QueueFigureExtractionService"
        ) as figure_service,
    ):
        QueueProcessDocumentService(
            document,
            should_run_l2_screening=True,
            should_run_parameter_extraction=True,
        ).perform()

    processing_request = DocumentProcessingRequest.objects.get()
    assert processing_request.citation == citation
    assert processing_request.should_run_l2_screening is True
    assert processing_request.should_run_parameter_extraction is True
    text_service.return_value.perform.assert_called_once_with()
    figure_service.return_value.perform.assert_called_once_with()


def test_queue_process_document_allows_extraction_only_without_configuration():
    document = DocumentFactory()
    citation = CitationFactory(document=document)

    with (
        patch("my_app.services.process_document.QueueTextExtractionService"),
        patch("my_app.services.process_document.QueueFigureExtractionService"),
    ):
        QueueProcessDocumentService(document).perform()

    processing_request = DocumentProcessingRequest.objects.get(
        citation=citation
    )
    assert processing_request.should_run_l2_screening is False
    assert processing_request.should_run_parameter_extraction is False


@pytest.mark.parametrize(
    ("service_kwargs", "error_message"),
    [
        (
            {"should_run_l2_screening": True},
            "L2 screening criteria must be configured",
        ),
        (
            {"should_run_parameter_extraction": True},
            "Parameters must be configured",
        ),
    ],
)
def test_queue_process_document_rejects_unconfigured_post_processing(
    service_kwargs,
    error_message,
):
    document = DocumentFactory()
    CitationFactory(document=document)

    with pytest.raises(MissingPreconditionError, match=error_message):
        QueueProcessDocumentService(document, **service_kwargs).perform()

    assert DocumentProcessingRequest.objects.count() == 0
