from django.tasks import task

from my_app.models import PdfFromDOIRequest
from my_app.services.doi_pdf_service import DoiPdfService


@task
def process_doi_pdf_request(request_id: int, run_id: str):
    result = (
        PdfFromDOIRequest.objects.select_related("citation")
        .filter(
            pk=request_id,
            run_id=run_id,
            status=PdfFromDOIRequest.Status.PENDING,
        )
        .first()
    )
    if result is None:
        return
    DoiPdfService(result.citation, run_id=run_id).perform()
