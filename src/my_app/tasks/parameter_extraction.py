from django.tasks import task

from data_fetcher.util import GlobalRequest, clear_request_caches

from my_app.services.parameter_extraction import (
    ProcessParameterExtractionService,
)


@task
def process_parameter_extraction_task(result_id: int):
    clear_request_caches()  # just in case
    with GlobalRequest():
        service = ProcessParameterExtractionService(result_id=result_id)
        service.perform()
