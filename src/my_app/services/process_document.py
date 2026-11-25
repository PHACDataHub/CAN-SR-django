from functools import partial

from django.db import transaction
from django.tasks import Task

from my_app.models import (
    Document,
    FigureExtractionResult,
    Phase2CitationWorkflowRequest,
    TextExtractionResult,
)
from my_app.services.task_cancellation import (
    current_cancellation_generation_id,
)
from shortcuts import logger


class QueueProcessDocumentService:
    """Queue missing text/figure extractions independently; callers check completion."""

    def __init__(
        self,
        document: Document,
        *,
        workflow_request: Phase2CitationWorkflowRequest | None = None,
        review_id: int | None = None,
    ) -> None:
        self.document = document
        self.workflow_request = workflow_request
        self.review_id = review_id

    def perform(self) -> tuple[TextExtractionResult, FigureExtractionResult]:
        from my_app.tasks.figure_extraction_task import (
            process_figure_extraction,
        )
        from my_app.tasks.text_extraction_task import (
            process_text_extraction_result,
        )

        with transaction.atomic():
            # Citations can share a document; serialize creation and dispatch decisions.
            document = Document.objects.select_for_update().get(
                pk=self.document.pk
            )
            review_id = self.review_id
            if self.workflow_request is None:
                cancellation_generation_id = (
                    current_cancellation_generation_id()
                )
            else:
                review_id = self.workflow_request.citation.dataset.review_id
                cancellation_generation_id = (
                    self.workflow_request.cancellation_generation_id
                )
            text_result, queue_text = self.prepare_result(
                TextExtractionResult, document
            )
            figure_result, queue_figures = self.prepare_result(
                FigureExtractionResult, document
            )
            if queue_text:
                transaction.on_commit(
                    partial(
                        self.enqueue,
                        process_text_extraction_result,
                        text_result,
                        review_id,
                        cancellation_generation_id,
                    )
                )
            if queue_figures:
                transaction.on_commit(
                    partial(
                        self.enqueue,
                        process_figure_extraction,
                        figure_result,
                        review_id,
                        cancellation_generation_id,
                    )
                )
        return text_result, figure_result

    def prepare_result[
        ResultT: (TextExtractionResult, FigureExtractionResult)
    ](self, result_model: type[ResultT], document: Document) -> tuple[
        ResultT, bool
    ]:
        result, created = result_model.objects.get_or_create(
            document=document,
            defaults={"workflow_request": self.workflow_request},
        )
        if result.status == "canceled":
            result.status = "pending"
            result.workflow_request = self.workflow_request
            result.save(update_fields=["status", "workflow_request"])
            return result, True
        return result, created

    @staticmethod
    def enqueue(
        task: Task,
        result: TextExtractionResult | FigureExtractionResult,
        review_id: int | None,
        cancellation_generation_id: int,
    ) -> None:
        try:
            task.enqueue(
                document_id=result.document_id,
                review_id=review_id,
                cancellation_generation_id=cancellation_generation_id,
            )
        except Exception:
            type(result).objects.filter(pk=result.pk).update(status="failed")
            logger.exception(
                "Could not dispatch %s id=%s", type(result).__name__, result.pk
            )
