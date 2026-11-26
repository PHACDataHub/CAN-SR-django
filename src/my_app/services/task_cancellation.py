from collections.abc import Iterable

from django.db import connection, transaction
from django.db.models import Max, Q, QuerySet
from django.utils import timezone

from my_app.models import (
    CancellationGeneration,
    L1CriticalScreeningResult,
    L1ScreeningResult,
    L2CriticalScreeningResult,
    L2ScreeningResult,
    ParameterExtractionResult,
    Review,
    ScreeningResultStatus,
)

type ScreeningOrParameterResult = (
    L1ScreeningResult
    | L1CriticalScreeningResult
    | L2ScreeningResult
    | L2CriticalScreeningResult
    | ParameterExtractionResult
)


def cancel_review_tasks(review: Review) -> CancellationGeneration:
    return _record_cancellation(review=review)


def cancel_all_tasks() -> CancellationGeneration:
    return _record_cancellation()


def _record_cancellation(
    *, review: Review | None = None
) -> CancellationGeneration:
    """
    why is this so weird? Because postgres allocates IDs before commit.

    Suppose,
        1. a global cancellation gets ID 10 and its transaction stalls
        2. Then, A review cancellation gets ID 11 and commits first
        3. A new task snapshots 11
    When the global cancellation finally commits,
    the task misses it because its entry check only looks for IDs > 11

    The lock serializes cancellation writes so that 11 can’t be allocated
    until the transaction holding 10 finishes. Ordinary task reads can continue
    """

    with transaction.atomic():
        if connection.vendor == "postgresql":
            # Keep cancellation IDs in commit order, without blocking readers.
            table = connection.ops.quote_name(
                CancellationGeneration._meta.db_table
            )
            with connection.cursor() as cursor:
                cursor.execute(
                    f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE"
                )
        return CancellationGeneration.objects.create(review=review)


def current_cancellation_generation_id() -> int:
    return CancellationGeneration.objects.aggregate(
        latest=Max("pk", default=0)
    )["latest"]


def task_was_canceled(
    cancellation_generation_id: int, *, review_ids: Iterable[int]
) -> bool:
    """Accept review IDs directly or as a single-column queryset."""
    return (
        CancellationGeneration.objects.filter(
            pk__gt=cancellation_generation_id
        )
        .filter(Q(review__isnull=True) | Q(review_id__in=review_ids))
        .exists()
    )


def abandon_pending_results_if_canceled(
    result_queryset: QuerySet[ScreeningOrParameterResult],
    *,
    review_ids: Iterable[int],
    cancellation_generation_id: int,
) -> bool:
    """Return whether the task should skip processing and abandon its pending results."""
    if not task_was_canceled(
        cancellation_generation_id, review_ids=review_ids
    ):
        return False
    result_queryset.filter(status=ScreeningResultStatus.PENDING).update(
        status=ScreeningResultStatus.ABANDONED, abandoned_at=timezone.now()
    )
    return True
