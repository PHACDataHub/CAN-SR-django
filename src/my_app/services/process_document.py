from proj.task_groups import gather_tasks, task_call
from proj.util import MissingPreconditionError

from my_app.models import Citation, Document
from my_app.queries import (
    is_l2_screening_defined,
    is_parameter_extraction_defined,
)
from my_app.services.figure_extraction_service import FigureExtractionService
from my_app.services.text_extraction import TextExtractionService
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
        from my_app.tasks.document_post_processing import (
            process_requested_document_post_processing,
        )
        from my_app.tasks.figure_extraction_task import (
            process_figure_extraction,
        )
        from my_app.tasks.text_extraction_task import (
            process_text_extraction_result,
        )

        TextExtractionService(self.document).prepare()
        FigureExtractionService(self.document).prepare()

        return gather_tasks(
            {
                "text_extraction": task_call(
                    process_text_extraction_result,
                    document_id=self.document.id,
                ),
                "figure_extraction": task_call(
                    process_figure_extraction,
                    document_id=self.document.id,
                ),
            },
            then=process_requested_document_post_processing,
            then_kwargs={
                "citation_id": self.citation.id,
                "should_run_l2_screening": self.should_run_l2_screening,
                "should_run_parameter_extraction": (
                    self.should_run_parameter_extraction
                ),
            },
            key=f"process-document:{self.document.id}",
        )
