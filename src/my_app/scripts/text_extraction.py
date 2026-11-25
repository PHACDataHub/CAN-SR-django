"""
This is used to debug the task

"""

from django.core.management import call_command

from my_app.services.task_cancellation import (
    current_cancellation_generation_id,
)
from my_app.tasks.text_extraction_task import process_text_extraction_result


def run(document_id):
    process_text_extraction(int(document_id))


def process_text_extraction(document_id):
    process_text_extraction_result.enqueue(
        document_id=document_id,
        cancellation_generation_id=current_cancellation_generation_id(),
    )
    call_command("db_worker", batch=True, reload=False)
