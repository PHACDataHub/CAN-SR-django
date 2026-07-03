from django.tasks import task

from my_app.services.l2_screening import ProcessL2ScreeningService


@task
def process_l2_screening_task(result_id: int):
    service = ProcessL2ScreeningService(result_id=result_id)
    service.perform()
