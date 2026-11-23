from django.tasks import task
from django.utils import timezone

from my_app.models import (
    L1CriticalScreeningResult,
    L1ScreeningResult,
    ScreeningResultStatus,
)
from my_app.services.l1_screening import ProcessL1ScreeningService


@task
def process_l1_screening_task(result_id: int):
    service = ProcessL1ScreeningService(result_id=result_id)
    try:
        service.perform()
    except Exception:
        L1CriticalScreeningResult.objects.filter(
            initial_result_id=result_id,
            initial_result__bulk_request__isnull=False,
            status=ScreeningResultStatus.PENDING,
        ).update(
            status=ScreeningResultStatus.ABANDONED, abandoned_at=timezone.now()
        )
        L1ScreeningResult.objects.filter(
            pk=result_id,
            bulk_request__isnull=False,
            status=ScreeningResultStatus.PENDING,
        ).update(
            status=ScreeningResultStatus.ABANDONED, abandoned_at=timezone.now()
        )
        raise


@task
def process_l1_critical_screening_task(result_id: int):
    from my_app.services.critical_screening import (
        ProcessL1CriticalScreeningService,
    )

    try:
        ProcessL1CriticalScreeningService(result_id).perform()
    except Exception:
        L1CriticalScreeningResult.objects.filter(
            pk=result_id,
            initial_result__bulk_request__isnull=False,
            status=ScreeningResultStatus.PENDING,
        ).update(
            status=ScreeningResultStatus.ABANDONED, abandoned_at=timezone.now()
        )
        raise
