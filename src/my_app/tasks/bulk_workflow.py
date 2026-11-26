from django.tasks import task

from my_app.services.bulk_workflow import check_bulk_workflow_result


@task
def check_bulk_workflow(request_id: int):
    check_bulk_workflow_result(request_id)
