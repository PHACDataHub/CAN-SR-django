from django.tasks import task

from my_app.services.document_post_processing import (
    RequestedDocumentPostProcessingService,
)


@task
def process_requested_document_post_processing(
    task_group_id: str,
    citation_id: int,
    should_run_l2_screening: bool,
    should_run_parameter_extraction: bool,
):
    RequestedDocumentPostProcessingService(
        task_group_id=task_group_id,
        citation_id=citation_id,
        should_run_l2_screening=should_run_l2_screening,
        should_run_parameter_extraction=should_run_parameter_extraction,
    ).perform()
