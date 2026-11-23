from functools import partial

from django.db import transaction

from my_app.models import (
    Document,
    FigureExtractionResult,
    TextExtractionResult,
)
from shortcuts import logger


class QueueProcessDocumentService:
    """Queue missing text/figure extractions independently; callers check completion."""

    def __init__(self, document: Document, *, workflow_request=None):
        self.document = document
        self.workflow_request = workflow_request

    def perform(self):
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
            text_result, text_created = (
                TextExtractionResult.objects.get_or_create(
                    document=document,
                    defaults={"workflow_request": self.workflow_request},
                )
            )
            figure_result, figure_created = (
                FigureExtractionResult.objects.get_or_create(
                    document=document,
                    defaults={"workflow_request": self.workflow_request},
                )
            )
            if text_created:
                transaction.on_commit(
                    partial(
                        self.enqueue,
                        process_text_extraction_result,
                        text_result,
                    )
                )
            if figure_created:
                transaction.on_commit(
                    partial(
                        self.enqueue, process_figure_extraction, figure_result
                    )
                )
        return text_result, figure_result

    @staticmethod
    def enqueue(task, result):
        try:
            task.enqueue(document_id=result.document_id)
        except Exception:
            type(result).objects.filter(pk=result.pk).update(status="failed")
            logger.exception(
                "Could not dispatch %s id=%s", type(result).__name__, result.pk
            )
