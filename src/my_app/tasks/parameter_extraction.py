from django.tasks import task
from django.utils import timezone

from data_fetcher.util import GlobalRequest, clear_request_caches

from my_app.models import ParameterExtractionResult, ScreeningResultStatus
from my_app.services.parameter_extraction import (
    ProcessParameterExtractionService,
)
from my_app.services.task_cancellation import (
    abandon_pending_results_if_canceled,
)


@task
def process_parameter_extraction_task(
    result_id: int, cancellation_generation_id: int = 0
) -> None:
    result_queryset = ParameterExtractionResult.objects.filter(pk=result_id)
    if abandon_pending_results_if_canceled(
        result_queryset,
        review_ids=result_queryset.values_list(
            "citation__dataset__review_id", flat=True
        ),
        cancellation_generation_id=cancellation_generation_id,
    ):
        return
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
