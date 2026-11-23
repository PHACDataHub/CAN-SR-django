from django.tasks import task
from django.utils import timezone

from my_app.models import (
    L2CriticalScreeningResult,
    L2ScreeningResult,
    ScreeningResultStatus,
)
from my_app.services.l2_screening import ProcessL2ScreeningService


@task
def process_l2_screening_task(result_id: int):
    service = ProcessL2ScreeningService(result_id=result_id)
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
def process_l2_critical_screening_task(result_id: int):
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
