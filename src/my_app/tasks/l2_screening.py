from django.tasks import task

from data_fetcher.util import GlobalRequest, clear_request_caches

from my_app.services.l2_screening import ProcessL2ScreeningService


@task
def process_l2_screening_task(result_id: int):
    clear_request_caches()  # just in case
    with GlobalRequest():
        service = ProcessL2ScreeningService(result_id=result_id)
        service.perform()
