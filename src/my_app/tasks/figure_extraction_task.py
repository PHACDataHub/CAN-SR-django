from django.tasks import task

from data_fetcher.util import GlobalRequest, clear_request_caches

from my_app.models import Document
from my_app.services.figure_extraction_service import FigureExtractionService


@task(takes_context=True)
def process_figure_extraction(context, document_id: int):
    clear_request_caches()  # just in case
    with GlobalRequest():
        service = FigureExtractionService(
            document=Document.objects.get(pk=document_id)
        )
        service.perform()
