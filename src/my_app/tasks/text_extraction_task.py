from django.tasks import task

from data_fetcher.util import GlobalRequest, clear_request_caches

from my_app.models import Document
from my_app.services.text_extraction import TextExtractionService


@task(takes_context=True)
def process_text_extraction_result(context, document_id: int):
    clear_request_caches()  # just in case
    with GlobalRequest():
        service = TextExtractionService(
            document=Document.objects.get(pk=document_id)
        )
        service.perform()
