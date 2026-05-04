from django.tasks import task

from my_app.models import SystematicReview


def _create_demo_task_run(
    *, task_result_id, kind, label, record_count, attempt
):
    from my_app.models import DemoTaskRun

    run = DemoTaskRun.objects.create(
        task_result_id=task_result_id,
        kind=kind,
        label=label,
        record_count=record_count,
        attempt=attempt,
    )

    return {
        "demo_task_run_id": run.id,
        "kind": kind,
        "label": label,
        "record_count": record_count,
        "attempt": attempt,
    }


async def _create_demo_task_run_async(
    *, task_result_id, kind, label, record_count, attempt
):
    from my_app.models import DemoTaskRun

    run = await DemoTaskRun.objects.acreate(
        task_result_id=task_result_id,
        kind=kind,
        label=label,
        record_count=record_count,
        attempt=attempt,
    )

    return {
        "demo_task_run_id": run.id,
        "kind": kind,
        "label": label,
        "record_count": record_count,
        "attempt": attempt,
    }


@task(backend="default", queue_name="default", takes_context=True)
def record_sr_snapshot(context, label: str):

    record_count = SystematicReview.objects.count()

    return _create_demo_task_run(
        task_result_id=context.task_result.id,
        kind="sync",
        label=label,
        record_count=record_count,
        attempt=context.attempt,
    )


@task(backend="default", queue_name="default", takes_context=True)
async def record_sr_snapshot_async(context, label: str, record_count: int):
    return await _create_demo_task_run_async(
        task_result_id=context.task_result.id,
        kind="async",
        label=label,
        record_count=record_count,
        attempt=context.attempt,
    )
