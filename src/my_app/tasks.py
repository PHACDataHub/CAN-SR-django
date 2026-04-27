from django.tasks import task


def _create_demo_task_run(
    *, task_result_id, kind, label, project_count, attempt
):
    from my_app.models import DemoTaskRun

    run = DemoTaskRun.objects.create(
        task_result_id=task_result_id,
        kind=kind,
        label=label,
        project_count=project_count,
        attempt=attempt,
    )

    return {
        "demo_task_run_id": run.id,
        "kind": kind,
        "label": label,
        "project_count": project_count,
        "attempt": attempt,
    }


async def _create_demo_task_run_async(
    *, task_result_id, kind, label, project_count, attempt
):
    from my_app.models import DemoTaskRun

    run = await DemoTaskRun.objects.acreate(
        task_result_id=task_result_id,
        kind=kind,
        label=label,
        project_count=project_count,
        attempt=attempt,
    )

    return {
        "demo_task_run_id": run.id,
        "kind": kind,
        "label": label,
        "project_count": project_count,
        "attempt": attempt,
    }


@task(backend="default", queue_name="default", takes_context=True)
def record_project_snapshot(context, label: str):
    from my_app.models import Project

    project_count = Project.objects.count()

    return _create_demo_task_run(
        task_result_id=context.task_result.id,
        kind="sync",
        label=label,
        project_count=project_count,
        attempt=context.attempt,
    )


@task(backend="default", queue_name="default", takes_context=True)
async def record_project_snapshot_async(
    context, label: str, project_count: int
):
    return await _create_demo_task_run_async(
        task_result_id=context.task_result.id,
        kind="async",
        label=label,
        project_count=project_count,
        attempt=context.attempt,
    )
