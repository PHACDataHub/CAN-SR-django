# this is a fake/testing-only task file

from django.tasks import task


@task
def check_task_group(task_group_id: str):
    from proj.task_groups import check_task_group_result

    check_task_group_result(task_group_id)
