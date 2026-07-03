from django.tasks import task

from my_app.services.l1_screening import ProcessL1ScreeningService


@task
def process_l1_screening_task(result_id: int):
    service = ProcessL1ScreeningService(result_id=result_id)
    service.perform()
