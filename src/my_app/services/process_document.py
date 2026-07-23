from proj.util import MissingPreconditionError

from my_app.models import Citation, Document, DocumentProcessingRequest
from my_app.queries import (
    is_l2_screening_defined,
    is_parameter_extraction_defined,
)
from my_app.services.figure_extraction_service import (
    QueueFigureExtractionService,
)
from my_app.services.text_extraction import QueueTextExtractionService
from shortcuts import cached_property, logger


class QueueProcessDocumentService:
    def __init__(
        self,
        document: Document,
        *,
        should_run_l2_screening: bool = False,
        should_run_parameter_extraction: bool = False,
    ):
        self.document = document
        self.should_run_l2_screening = should_run_l2_screening
        self.should_run_parameter_extraction = should_run_parameter_extraction

    @cached_property
    def citation(self):
        return Citation.objects.get(document=self.document)

    def validate(self, citation: Citation):
        if self.should_run_l2_screening and not is_l2_screening_defined(
            citation.id
        ):
            raise MissingPreconditionError(
                "L2 screening criteria must be configured before requesting "
                "automatic L2 screening."
            )

        if (
            self.should_run_parameter_extraction
            and not is_parameter_extraction_defined(citation.id)
        ):
            raise MissingPreconditionError(
                "Parameters must be configured before requesting automatic "
                "parameter extraction."
            )

    def perform(self):
        logger.info(
            "QueueProcessDocumentService started for document_id=%s",
            self.document.id,
        )

        self.validate(self.citation)
        DocumentProcessingRequest.objects.create(
            citation=self.citation,
            should_run_l2_screening=self.should_run_l2_screening,
            should_run_parameter_extraction=(
                self.should_run_parameter_extraction
            ),
        )

        QueueTextExtractionService(self.document).perform()
        QueueFigureExtractionService(self.document).perform()
