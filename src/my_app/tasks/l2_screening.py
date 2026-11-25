from django.tasks import task
from django.utils import timezone

from my_app.models import (
    L2CriticalScreeningResult,
    L2ScreeningResult,
    ScreeningResultStatus,
)
from my_app.services.l2_screening import ProcessL2ScreeningService
from my_app.services.task_cancellation import (
    abandon_pending_results_if_canceled,
)


@task
def process_l2_screening_task(
    result_id: int, cancellation_generation_id: int = 0
) -> None:
    result_queryset = L2ScreeningResult.objects.filter(pk=result_id)
    if abandon_pending_results_if_canceled(
        result_queryset,
        review_ids=result_queryset.values_list(
            "citation__dataset__review_id", flat=True
        ),
        cancellation_generation_id=cancellation_generation_id,
    ):
        return
    service = ProcessL2ScreeningService(
        result_id=result_id,
        cancellation_generation_id=cancellation_generation_id,
    )
    try:
        service.perform()
    except Exception:
        L2CriticalScreeningResult.objects.filter(
            initial_result_id=result_id,
            initial_result__workflow_request__isnull=False,
            status=ScreeningResultStatus.PENDING,
        ).update(
            status=ScreeningResultStatus.ABANDONED, abandoned_at=timezone.now()
        )
        L2ScreeningResult.objects.filter(
            pk=result_id,
            workflow_request__isnull=False,
            status=ScreeningResultStatus.PENDING,
        ).update(
            status=ScreeningResultStatus.ABANDONED, abandoned_at=timezone.now()
        )
        raise


@task
def process_l2_critical_screening_task(
    result_id: int, cancellation_generation_id: int = 0
) -> None:
    result_queryset = L2CriticalScreeningResult.objects.filter(pk=result_id)
    if abandon_pending_results_if_canceled(
        result_queryset,
        review_ids=result_queryset.values_list(
            "initial_result__citation__dataset__review_id", flat=True
        ),
        cancellation_generation_id=cancellation_generation_id,
    ):
        return
    from my_app.services.critical_screening import (
        ProcessL2CriticalScreeningService,
    )

    try:
        ProcessL2CriticalScreeningService(result_id).perform()
    except Exception:
        L2CriticalScreeningResult.objects.filter(
            pk=result_id,
            initial_result__workflow_request__isnull=False,
            status=ScreeningResultStatus.PENDING,
        ).update(
            status=ScreeningResultStatus.ABANDONED, abandoned_at=timezone.now()
        )
        raise
