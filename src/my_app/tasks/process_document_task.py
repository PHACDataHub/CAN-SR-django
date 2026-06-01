from django.tasks import task

from data_fetcher.util import GlobalRequest, clear_request_caches

from my_app.models import Document
from my_app.services.preprocess_pdf import PreprocessPDFService


@task(takes_context=True)
def process_document_metadata(context, document_id: int):
    clear_request_caches()  # just in case
    with GlobalRequest():
        service = PreprocessPDFService(
            document=Document.objects.get(pk=document_id)
        )
        service.perform()
