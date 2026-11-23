from django.tasks import task
from django.utils import timezone

from data_fetcher.util import GlobalRequest, clear_request_caches

from my_app.models import ParameterExtractionResult, ScreeningResultStatus
from my_app.services.parameter_extraction import (
    ProcessParameterExtractionService,
)


@task
def process_parameter_extraction_task(result_id: int):
    clear_request_caches()  # just in case
    with GlobalRequest():
        service = ProcessParameterExtractionService(result_id=result_id)
        try:
            service.perform()
        except Exception:
            ParameterExtractionResult.objects.filter(
                pk=result_id,
                bulk_request__isnull=False,
                status=ScreeningResultStatus.PENDING,
            ).update(
                status=ScreeningResultStatus.ABANDONED,
                abandoned_at=timezone.now(),
            )
            raise
