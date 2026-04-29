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

from my_app.models import Document, DocumentMetadata
from my_app.tasks.process_document_task import process_document_metadata


def run(document_id):
    process_document(int(document_id))


def process_document(document_id):
    res = process_document_metadata.enqueue(document_id=document_id)
    process_one_task()
