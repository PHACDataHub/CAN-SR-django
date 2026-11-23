from django.tasks import task

from my_app.services.phase2_workflow import (
    check_bulk_workflow_result,
    check_citation_workflow_result,
)


@task
def check_citation_workflow(request_id: int):
    check_citation_workflow_result(request_id)


@task
def check_bulk_workflow(request_id: int):
    check_bulk_workflow_result(request_id)
