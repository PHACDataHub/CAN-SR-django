from collections.abc import Iterable

from django.tasks import task

from my_app.models import Document, TextExtractionResult, TextExtractionStatus
from my_app.services.task_cancellation import task_was_canceled
from my_app.services.text_extraction import TextExtractionService


@task
def process_text_extraction_result(
    document_id: int,
    cancellation_generation_id: int = 0,
    review_id: int | None = None,
) -> None:
    document = Document.objects.get(pk=document_id)
    review_ids: Iterable[int]
    if review_id is None:
        review_ids = document.citations.values_list(
            "dataset__review_id", flat=True
        )
    else:
        review_ids = [review_id]
    if task_was_canceled(cancellation_generation_id, review_ids=review_ids):
        TextExtractionResult.objects.filter(
            document=document, status=TextExtractionStatus.PENDING
        ).update(status=TextExtractionStatus.CANCELED)
        return
    service = TextExtractionService(document=document)
    service.perform()
