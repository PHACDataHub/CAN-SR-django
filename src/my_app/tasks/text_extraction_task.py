from django.tasks import task

from my_app.models import Document
from my_app.services.text_extraction import TextExtractionService


@task
def process_text_extraction_result(document_id: int):
    service = TextExtractionService(
        document=Document.objects.get(pk=document_id)
    )
    service.perform()
