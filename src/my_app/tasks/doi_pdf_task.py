import logging

from django.tasks import task
from django.utils import timezone

from proj.util import MissingPreconditionError

from my_app.models import PdfFromDOIRequest
from my_app.services.doi_pdf_service import (
    DoiPdfError,
    DoiPdfService,
    log_doi_pdf_event,
)
from my_app.services.task_cancellation import task_was_canceled


@task
def process_doi_pdf_request(
    request_id: int, run_id: str, cancellation_generation_id: int = 0
):
    run_id = str(run_id)
    context = {"request_id": request_id, "run_id": run_id}
    log_doi_pdf_event("task_started", **context)
    stage = "load_request"
    try:
        result = (
            PdfFromDOIRequest.objects.select_related("citation__dataset")
            .filter(pk=request_id)
            .first()
        )
        if result is None:
            log_doi_pdf_event("task_request_missing", **context)
            return
        context["citation_id"] = result.citation_id
        if str(result.run_id) != run_id:
            log_doi_pdf_event(
                "task_run_superseded",
                **context,
                current_run_id=str(result.run_id),
            )
            return
        if result.status != result.Status.PENDING:
            log_doi_pdf_event(
                "task_not_pending", **context, status=result.status
            )
            return
        if task_was_canceled(
            cancellation_generation_id,
            review_ids=[result.citation.dataset.review_id],
        ):
            PdfFromDOIRequest.objects.filter(
                pk=request_id, run_id=run_id, status=result.Status.PENDING
            ).update(status=result.Status.CANCELED, updated_dt=timezone.now())
            log_doi_pdf_event("task_canceled", **context)
            return
        stage = "process_request"
        outcome = DoiPdfService(result.citation, run_id=run_id).perform()
    except Exception as exc:
        log_doi_pdf_event(
            f"task_{stage}_failed",
            level=logging.ERROR,
            exc_info=not isinstance(
                exc, (DoiPdfError, MissingPreconditionError)
            ),
            **context,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise
    log_doi_pdf_event("task_finished", **context, status=outcome.status)
