"""
This is used to debug the task

Alternatively, use the view
"""

from django.core.management import call_command

from django_database_task import (
    get_pending_task_count,
    process_one_task,
    process_tasks,
    run_task_by_id,
)

from my_app.models import Document, TextExtractionResult
from my_app.tasks.text_extraction_task import process_text_extraction_result


def run(document_id):
    process_text_extraction(int(document_id))


def process_text_extraction(document_id):
    res = process_text_extraction_result.enqueue(document_id=document_id)
    process_one_task()
