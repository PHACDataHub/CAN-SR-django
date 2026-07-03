from django.tasks import task

from my_app.models import Document
from my_app.services.figure_extraction_service import FigureExtractionService


@task
def process_figure_extraction(document_id: int):
    service = FigureExtractionService(
        document=Document.objects.get(pk=document_id)
    )
    service.perform()
